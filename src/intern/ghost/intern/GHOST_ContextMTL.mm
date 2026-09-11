/* SPDX-FileCopyrightText: 2013 Blender Authors
 * SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup GHOST
 *
 * Definition of GHOST_ContextMTL class.
 *
 * Mixar overlay of upstream intern/ghost/intern/GHOST_ContextMTL.mm
 * (pin v5.2.0). The present blit keeps the sampled framebuffer alpha so a
 * non-opaque CAMetalLayer can composite over the theme-frame frost sibling.
 * Re-diff against upstream after every pin bump.
 */

/* Don't generate OpenGL deprecation warning. This is a known thing, and is not something easily
 * solvable in a short term. */
#ifdef __clang__
#  pragma clang diagnostic ignored "-Wdeprecated-declarations"
#endif

#include "GHOST_ContextMTL.hh"
#include "GHOST_MixarGlassCocoa.hh"

#import <Cocoa/Cocoa.h>
#import <Metal/Metal.h>
#import <QuartzCore/QuartzCore.h>
#import <objc/runtime.h>

#include <cassert>
#include <mutex>
#include <vector>

static const MTLPixelFormat METAL_FRAMEBUFFERPIXEL_FORMAT_EDR = MTLPixelFormatRGBA16Float;
static const void *kMixarPresentFmtKey = &kMixarPresentFmtKey;

static void ghost_fatal_error_dialog(const char *msg);

static MTLPixelFormat mixar_present_fmt(CAMetalLayer *layer)
{
  NSNumber *n = objc_getAssociatedObject(layer, kMixarPresentFmtKey);
  return n ? MTLPixelFormat(n.unsignedIntegerValue) : MTLPixelFormatInvalid;
}

static void mixar_present_fmt_set(CAMetalLayer *layer, MTLPixelFormat fmt)
{
  objc_setAssociatedObject(
      layer, kMixarPresentFmtKey, @(fmt), OBJC_ASSOCIATION_RETAIN_NONATOMIC);
}

static id<MTLRenderPipelineState> mixar_new_present_pipeline(id<MTLDevice> device,
                                                             MTLPixelFormat format)
{
  NSString *source = @R"msl(
      using namespace metal;

      struct Vertex {
        float4 position [[position]];
        float2 texCoord [[attribute(0)]];
      };

      vertex Vertex vertex_shader(uint v_id [[vertex_id]]) {
        Vertex vtx;
        vtx.position.x = float(v_id & 1) * 4.0 - 1.0;
        vtx.position.y = float(v_id >> 1) * 4.0 - 1.0;
        vtx.position.z = 0.0;
        vtx.position.w = 1.0;
        vtx.texCoord = vtx.position.xy * 0.5 + 0.5;
        return vtx;
      }

      constexpr sampler s {};

      fragment float4 fragment_shader(Vertex v [[stage_in]],
                      texture2d<float> t [[texture(0)]]) {
        /* Keep sampled alpha and premultiply. WindowServer composites
         * CAMetalLayer as premultiplied; RGB with A=0 is treated as an
         * opaque slab. Opaque windows already carry A=1, so this is a
         * no-op there. */
        float4 out_tex = t.sample(s, v.texCoord);
        out_tex.rgb = min(out_tex.rgb, 16384.0) * out_tex.a;
        return out_tex;
      }
    )msl";

  MTLCompileOptions *options = [[[MTLCompileOptions alloc] init] autorelease];
  options.languageVersion = MTLLanguageVersion1_1;
  NSError *error = nil;
  id<MTLLibrary> library = [device newLibraryWithSource:source options:options error:&error];
  if (error) {
    ghost_fatal_error_dialog(
        "GHOST_ContextMTL: newLibraryWithSource:options:error: failed!");
  }

  MTLRenderPipelineDescriptor *desc = [[[MTLRenderPipelineDescriptor alloc] init] autorelease];
  desc.fragmentFunction = [library newFunctionWithName:@"fragment_shader"];
  desc.vertexFunction = [library newFunctionWithName:@"vertex_shader"];
  [desc.colorAttachments objectAtIndexedSubscript:0].pixelFormat = format;
  [library autorelease];

  id<MTLRenderPipelineState> pipeline = [device newRenderPipelineStateWithDescriptor:desc
                                                                               error:&error];
  if (error) {
    ghost_fatal_error_dialog(
        "GHOST_ContextMTL: newRenderPipelineStateWithDescriptor:error: failed!");
  }
  [desc.fragmentFunction release];
  [desc.vertexFunction release];
  return pipeline;
}

static void ghost_fatal_error_dialog(const char *msg)
{
  @autoreleasepool {
    NSString *message = [NSString stringWithFormat:@"Error opening window:\n%s", msg];

    NSAlert *alert = [[NSAlert alloc] init];

    alert.messageText = @"Blender";
    alert.informativeText = message;
    alert.alertStyle = NSAlertStyleCritical;

    [alert addButtonWithTitle:@"Quit"];
    [alert runModal];
  }

  exit(1);
}

MTLCommandQueue *GHOST_ContextMTL::s_sharedMetalCommandQueue = nil;
int GHOST_ContextMTL::s_sharedCount = 0;

GHOST_ContextMTL::GHOST_ContextMTL(const GHOST_ContextParams &context_params,
                                   NSView *metalView,
                                   CAMetalLayer *metalLayer)
    : GHOST_Context(context_params),
      metal_view_(metalView),
      metal_layer_(metalLayer),
      metal_render_pipeline_(nil)
{
  @autoreleasepool {
    /* Initialize Metal Swap-chain. */
    current_swapchain_index = 0;
    for (int i = 0; i < METAL_SWAPCHAIN_SIZE; i++) {
      default_framebuffer_metal_texture_[i].texture = nil;
      default_framebuffer_metal_texture_[i].index = i;
    }

    if (metal_view_) {
      owns_metal_device_ = false;
      metalInit();
    }
    else {
      /* Prepare offscreen GHOST Context Metal device. */
      id<MTLDevice> metalDevice = MTLCreateSystemDefaultDevice();

      if (context_params_.is_debug) {
        printf("Selected Metal Device: %s\n", [metalDevice.name UTF8String]);
      }

      owns_metal_device_ = true;
      if (metalDevice) {
        metal_layer_ = [[CAMetalLayer alloc] init];
        metal_layer_.edgeAntialiasingMask = 0;
        metal_layer_.masksToBounds = NO;
        metal_layer_.opaque = YES;
        metal_layer_.framebufferOnly = YES;
        metal_layer_.presentsWithTransaction = NO;
        [metal_layer_ removeAllAnimations];
        metal_layer_.device = metalDevice;
        metal_layer_.allowsNextDrawableTimeout = NO;

        {
          const GHOST_TVSyncModes vsync = getVSync();
          if (vsync != GHOST_kVSyncModeUnset) {
            metal_layer_.displaySyncEnabled = (vsync == GHOST_kVSyncModeOff) ? NO : YES;
          }
        }

        /* Enable EDR support. This is done by:
         * 1. Using a floating point render target, so that values outside 0..1 can be used
         * 2. Informing the OS that we are EDR aware, and intend to use values outside 0..1
         * 3. Setting the extended sRGB color space so that the OS knows how to interpret the
         *    values.
         */
        metal_layer_.wantsExtendedDynamicRangeContent = YES;
        metal_layer_.pixelFormat = METAL_FRAMEBUFFERPIXEL_FORMAT_EDR;
        const CFStringRef name = kCGColorSpaceExtendedSRGB;
        CGColorSpaceRef colorspace = CGColorSpaceCreateWithName(name);
        metal_layer_.colorspace = colorspace;
        CGColorSpaceRelease(colorspace);

        metalInit();
      }
      else {
        ghost_fatal_error_dialog(
            "[ERROR] Failed to create Metal device for offscreen GHOST Context.\n");
      }
    }

    /* Initialize swap-interval. */
    mtl_SwapInterval = 60;
  }
}

GHOST_ContextMTL::~GHOST_ContextMTL()
{
  /* Multiple threads can release their own context at the same time. */
  static std::mutex mutex;
  std::scoped_lock lock(mutex);

  metalFree();

  if (owns_metal_device_) {
    if (metal_layer_) {
      [metal_layer_ release];
      metal_layer_ = nil;
    }
  }
  assert(s_sharedCount);

  s_sharedCount--;
  [s_sharedMetalCommandQueue release];
  if (s_sharedCount == 0) {
    s_sharedMetalCommandQueue = nil;
  }
}

GHOST_TSuccess GHOST_ContextMTL::swapBufferRelease()
{
  if (metal_view_) {
    metalSwapBuffers();
  }
  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_ContextMTL::setSwapInterval(int interval)
{
  mtl_SwapInterval = interval;
  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_ContextMTL::getSwapInterval(int &interval_out)
{
  interval_out = mtl_SwapInterval;
  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_ContextMTL::activateDrawingContext()
{
  active_context_ = this;
  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_ContextMTL::releaseDrawingContext()
{
  active_context_ = nullptr;
  return GHOST_kSuccess;
}

unsigned int GHOST_ContextMTL::getDefaultFramebuffer()
{
  /* NOTE(Metal): This is not valid. */
  return 0;
}

GHOST_TSuccess GHOST_ContextMTL::updateDrawingContext()
{
  if (metal_view_) {
    metalUpdateFramebuffer();
    return GHOST_kSuccess;
  }
  return GHOST_kFailure;
}

id<MTLTexture> GHOST_ContextMTL::metalOverlayTexture()
{
  /* Increment Swap-chain - Only needed if context is requesting a new texture */
  current_swapchain_index = (current_swapchain_index + 1) % METAL_SWAPCHAIN_SIZE;

  /* Ensure backing texture is ready for current swapchain index */
  updateDrawingContext();

  /* Return texture. */
  return default_framebuffer_metal_texture_[current_swapchain_index].texture;
}

MTLCommandQueue *GHOST_ContextMTL::metalCommandQueue()
{
  return s_sharedMetalCommandQueue;
}
MTLDevice *GHOST_ContextMTL::metalDevice()
{
  id<MTLDevice> device = metal_layer_.device;
  return (MTLDevice *)device;
}

void GHOST_ContextMTL::metalRegisterPresentCallback(void (*callback)(
    MTLRenderPassDescriptor *, id<MTLRenderPipelineState>, id<MTLTexture>, id<CAMetalDrawable>))
{
  this->contextPresentCallback = callback;
}

void GHOST_ContextMTL::metalRegisterXrBlitCallback(
    void (*callback)(id<MTLTexture>, int, int, int, int))
{
  this->xrBlitCallback = callback;
}

GHOST_TSuccess GHOST_ContextMTL::initializeDrawingContext()
{
  @autoreleasepool {
    if (metal_view_) {
      metalInitFramebuffer();
    }
  }
  active_context_ = this;
  return GHOST_kSuccess;
}

GHOST_TSuccess GHOST_ContextMTL::releaseNativeHandles()
{
  metal_view_ = nil;

  return GHOST_kSuccess;
}

void GHOST_ContextMTL::metalInit()
{
  @autoreleasepool {
    id<MTLDevice> device = metal_layer_.device;

    /* Create a command queue for blit/present operation.
     * NOTE: All context should share a single command queue
     * to ensure correct ordering of work submitted from multiple contexts. */
    if (s_sharedMetalCommandQueue == nil) {
      s_sharedMetalCommandQueue = (MTLCommandQueue *)[device
          newCommandQueueWithMaxCommandBufferCount:GHOST_ContextMTL::max_command_buffer_count];
    }
    /* Ensure active GHOSTContext retains a reference to the shared context. */
    [s_sharedMetalCommandQueue retain];
    s_sharedCount++;

    const MTLPixelFormat format = metal_layer_.pixelFormat;
    metal_render_pipeline_ = (MTLRenderPipelineState *)mixar_new_present_pipeline(device,
                                                                                  format);
    mixar_present_fmt_set(metal_layer_, format);
  }
}

void GHOST_ContextMTL::metalFree()
{
  if (metal_render_pipeline_) {
    [metal_render_pipeline_ release];
    metal_render_pipeline_ = nil;
  }

  for (int i = 0; i < METAL_SWAPCHAIN_SIZE; i++) {
    if (default_framebuffer_metal_texture_[i].texture) {
      [default_framebuffer_metal_texture_[i].texture release];
      default_framebuffer_metal_texture_[i].texture = nil;
    }
  }
}

void GHOST_ContextMTL::metalInitFramebuffer()
{
  updateDrawingContext();
}

void GHOST_ContextMTL::metalUpdateFramebuffer()
{
  @autoreleasepool {
    /* Island/pill set the NSWindow non-opaque before this layer exists.
     * Re-apply on every size/format pass so an EDR overlay cannot outlive
     * the BGRA8 layer WindowServer will actually composite. */
    if (metal_view_ != nil && metal_view_.window != nil && !metal_view_.window.opaque) {
      Mixar_CocoaGlassAllowMetalAlpha(metal_view_);
    }

    const NSSize drawableSize = metal_layer_.drawableSize;
    const size_t width = size_t(drawableSize.width);
    const size_t height = size_t(drawableSize.height);

    /* The overlay is what Blender's GPU backend draws into. It stays
     * RGBA16Float even when the CAMetalLayer is BGRA8 — a format switch
     * here leaves the backend writing into a target it did not create,
     * and the island presents as an empty hole. Present converts. */
    if (default_framebuffer_metal_texture_[current_swapchain_index].texture &&
        default_framebuffer_metal_texture_[current_swapchain_index].texture.width == width &&
        default_framebuffer_metal_texture_[current_swapchain_index].texture.height == height)
    {
      return;
    }

    /* Free old texture */
    [default_framebuffer_metal_texture_[current_swapchain_index].texture release];

    id<MTLDevice> device = metal_layer_.device;
    MTLTextureDescriptor *overlayDesc = [MTLTextureDescriptor
        texture2DDescriptorWithPixelFormat:METAL_FRAMEBUFFERPIXEL_FORMAT_EDR
                                     width:width
                                    height:height
                                 mipmapped:NO];
    overlayDesc.storageMode = MTLStorageModePrivate;
    overlayDesc.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead;

    id<MTLTexture> overlayTex = [device newTextureWithDescriptor:overlayDesc];
    if (!overlayTex) {
      ghost_fatal_error_dialog(
          "GHOST_ContextMTL::metalUpdateFramebuffer: failed to create Metal overlay texture!");
    }
    else {
      overlayTex.label = [NSString
          stringWithFormat:@"Metal Overlay for GHOST Context %p", this];  //@"";
    }

    default_framebuffer_metal_texture_[current_swapchain_index].texture = overlayTex;

    /* Clear texture on create */
    id<MTLCommandBuffer> cmdBuffer = [s_sharedMetalCommandQueue commandBuffer];
    MTLRenderPassDescriptor *passDescriptor = [MTLRenderPassDescriptor renderPassDescriptor];
    {
      auto attachment = [passDescriptor.colorAttachments objectAtIndexedSubscript:0];
      attachment.texture = default_framebuffer_metal_texture_[current_swapchain_index].texture;
      attachment.loadAction = MTLLoadActionClear;
      attachment.clearColor = MTLClearColorMake(
          0.294, 0.294, 0.294, metal_layer_.opaque ? 1.000 : 0.000);
      attachment.storeAction = MTLStoreActionStore;
    }
    {
      id<MTLRenderCommandEncoder> enc = [cmdBuffer
          renderCommandEncoderWithDescriptor:passDescriptor];
      [enc endEncoding];
    }
    [cmdBuffer commit];

    metal_layer_.drawableSize = CGSizeMake(CGFloat(width), CGFloat(height));
  }
}

void GHOST_ContextMTL::metalSwapBuffers()
{
  @autoreleasepool {
    if (metal_view_ != nil && metal_view_.window != nil && !metal_view_.window.opaque) {
      Mixar_CocoaGlassAllowMetalAlpha(metal_view_);
    }
    const MTLPixelFormat format = metal_layer_.pixelFormat;
    if (mixar_present_fmt(metal_layer_) != format) {
      [metal_render_pipeline_ release];
      metal_render_pipeline_ = (MTLRenderPipelineState *)mixar_new_present_pipeline(
          metal_layer_.device, format);
      mixar_present_fmt_set(metal_layer_, format);
    }

    updateDrawingContext();

    id<CAMetalDrawable> drawable = [metal_layer_ nextDrawable];
    if (!drawable) {
      return;
    }

    MTLRenderPassDescriptor *passDescriptor = [MTLRenderPassDescriptor renderPassDescriptor];
    {
      auto attachment = [passDescriptor.colorAttachments objectAtIndexedSubscript:0];
      attachment.texture = drawable.texture;
      attachment.loadAction = MTLLoadActionClear;
      attachment.clearColor = MTLClearColorMake(0.0, 0.0, 0.0, metal_layer_.opaque ? 1.0 : 0.0);
      attachment.storeAction = MTLStoreActionStore;
    }

    assert(contextPresentCallback);
    assert(default_framebuffer_metal_texture_[current_swapchain_index].texture != nil);
    (*contextPresentCallback)(passDescriptor,
                              (id<MTLRenderPipelineState>)metal_render_pipeline_,
                              default_framebuffer_metal_texture_[current_swapchain_index].texture,
                              drawable);
  }
}
