# SPDX-FileCopyrightText: 2011-2022 Blender Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

string(TIMESTAMP CURRENT_YEAR "%Y")

set(PROJECT_DESCRIPTION  "Mixar - Advanced 3D Content Creation Suite")
set(PROJECT_COPYRIGHT    "Copyright (C) 2025-${CURRENT_YEAR} Mixar")
set(PROJECT_CONTACT      "support@mixar.app")
set(PROJECT_VENDOR       "Mixar")

# Use Mixar app version from environment (set by settings.bat from mixar.json),
# falling back to Blender version if not available.
if(DEFINED ENV{MIXAR_VERSION})
  string(REPLACE "." ";" _mixar_ver_parts "$ENV{MIXAR_VERSION}")
  list(GET _mixar_ver_parts 0 MAJOR_VERSION)
  list(GET _mixar_ver_parts 1 MINOR_VERSION)
  list(LENGTH _mixar_ver_parts _mixar_ver_len)
  if(_mixar_ver_len GREATER 2)
    list(GET _mixar_ver_parts 2 PATCH_VERSION)
  else()
    set(PATCH_VERSION 0)
  endif()
else()
  set(MAJOR_VERSION ${BLENDER_VERSION_MAJOR})
  set(MINOR_VERSION ${BLENDER_VERSION_MINOR})
  set(PATCH_VERSION ${BLENDER_VERSION_PATCH})
endif()

set(CPACK_SYSTEM_NAME ${CMAKE_SYSTEM_NAME})
set(CPACK_PACKAGE_DESCRIPTION ${PROJECT_DESCRIPTION})
set(CPACK_PACKAGE_VENDOR ${PROJECT_VENDOR})
set(CPACK_PACKAGE_CONTACT ${PROJECT_CONTACT})
set(CPACK_RESOURCE_FILE_LICENSE "${CMAKE_SOURCE_DIR}/COPYING")
set(CPACK_PACKAGE_INSTALL_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}")
set(CPACK_PACKAGE_VERSION_MAJOR "${MAJOR_VERSION}")
set(CPACK_PACKAGE_VERSION_MINOR "${MINOR_VERSION}")
set(CPACK_PACKAGE_VERSION_PATCH "${PATCH_VERSION}")


# Get the build revision, note that this can get out-of-sync, so for packaging run cmake first.
set(MY_WC_HASH "unknown")
if(EXISTS ${CMAKE_SOURCE_DIR}/.git/)
  find_package(Git)
  if(GIT_FOUND)
    execute_process(
      COMMAND git rev-parse --short=12 HEAD
      WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
      OUTPUT_VARIABLE MY_WC_HASH
      OUTPUT_STRIP_TRAILING_WHITESPACE
      ERROR_QUIET
    )
  endif()
endif()
set(BUILD_REV ${MY_WC_HASH})
unset(MY_WC_HASH)


# Force Package Name
execute_process(COMMAND date "+%Y%m%d" OUTPUT_VARIABLE CPACK_DATE OUTPUT_STRIP_TRAILING_WHITESPACE)
string(TOLOWER ${PROJECT_NAME} PROJECT_NAME_LOWER)
if(MSVC)
  if("${CMAKE_SIZEOF_VOID_P}" EQUAL "8")
    set(PACKAGE_ARCH windows64)
  else()
    set(PACKAGE_ARCH windows32)
  endif()
else()
  set(PACKAGE_ARCH ${CMAKE_SYSTEM_PROCESSOR})
endif()

if(CPACK_OVERRIDE_PACKAGENAME)
  set(CPACK_PACKAGE_FILE_NAME ${CPACK_OVERRIDE_PACKAGENAME})
else()
  set(CPACK_PACKAGE_FILE_NAME ${PROJECT_NAME_LOWER}-${MAJOR_VERSION}.${MINOR_VERSION}.${PATCH_VERSION}-git${CPACK_DATE}.${BUILD_REV}-${PACKAGE_ARCH})
endif()

if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
  # RPM packages
  include(build_files/cmake/RpmBuild.cmake)
  if(RPMBUILD_FOUND)
    set(CPACK_GENERATOR "RPM")
    set(CPACK_RPM_PACKAGE_RELEASE "git${CPACK_DATE}.${BUILD_REV}")
    set(CPACK_SET_DESTDIR "true")
    set(CPACK_PACKAGE_DESCRIPTION_SUMMARY "${PROJECT_DESCRIPTION}")
    set(CPACK_PACKAGE_RELOCATABLE "false")
    set(CPACK_RPM_PACKAGE_LICENSE "GPLv2+ and Apache 2.0")
    set(CPACK_RPM_PACKAGE_GROUP "Amusements/Multimedia")
    set(CPACK_RPM_USER_BINARY_SPECFILE "${CMAKE_SOURCE_DIR}/build_files/package_spec/rpm/blender.spec.in")
  endif()
endif()

# Mac Bundle
if(APPLE)
  set(CPACK_GENERATOR "DragNDrop")

  # Libraries are bundled directly
  set(CPACK_COMPONENT_LIBRARIES_HIDDEN TRUE)
endif()

if(WIN32)
  # Install location and upgrade identity are deliberately version-INDEPENDENT.
  #
  # Both used to embed MAJOR.MINOR ("Mixar/Mixar 3.3"), and because the WiX
  # UpgradeCode below is derived from this string, it changed on every minor
  # release. A 3.3.x -> 3.4.0 MSI then did not upgrade anything: it installed a
  # second copy in a second directory, left the old product in Apps & Features,
  # and the in-app updater relaunched whichever build the previous path pointed
  # at — an "update" that silently kept running the old version. One directory
  # and one UpgradeCode make every release a true major upgrade, which is what
  # restart-to-update depends on. Installs made under the old scheme are
  # removed by the legacy <Upgrade> rows generated below.
  set(CPACK_PACKAGE_INSTALL_DIRECTORY "Mixar")
  set(CPACK_PACKAGE_INSTALL_REGISTRY_KEY "Mixar")

  set(CPACK_NSIS_MUI_ICON ${CMAKE_SOURCE_DIR}/release/windows/icons/winmixar.ico)
  set(CPACK_NSIS_COMPRESSOR "/SOLID lzma")

  # Even though we no longer display this, we still need to set it otherwise it'll throw an error
  # during the msi build.
  set(CPACK_RESOURCE_FILE_LICENSE ${CMAKE_SOURCE_DIR}/release/license/spdx/GPL-3.0-or-later.txt)
  set(CPACK_WIX_PRODUCT_ICON ${CMAKE_SOURCE_DIR}/release/windows/icons/winmixar.ico)

  set(MIXAR_NAMESPACE_GUID "A83F2E1B-7C4D-4E5F-9B6A-1D2E3F4A5B6C")

  # Never derive this from a version: the UpgradeCode is the product's stable
  # identity across releases.
  string(UUID CPACK_WIX_UPGRADE_GUID
    NAMESPACE ${MIXAR_NAMESPACE_GUID}
    NAME "Mixar"
    TYPE SHA1 UPPER
  )

  # Legacy per-minor-version UpgradeCodes, from when the install directory was
  # "Mixar/Mixar <major>.<minor>". Listing them as removable upgrades is what
  # migrates an existing user onto the single install: without it they would
  # end up running the new build with the old one still installed beside it.
  # Generated rather than hand-listed so no shipped minor version is missed.
  set(MIXAR_LEGACY_UPGRADE_XML "")
  foreach(_legacy_major RANGE 1 ${MAJOR_VERSION})
    foreach(_legacy_minor RANGE 0 20)
      string(UUID _legacy_guid
        NAMESPACE ${MIXAR_NAMESPACE_GUID}
        NAME "Mixar/Mixar ${_legacy_major}.${_legacy_minor}"
        TYPE SHA1 UPPER
      )
      string(APPEND MIXAR_LEGACY_UPGRADE_XML
        "    <Upgrade Id=\"${_legacy_guid}\">\n"
        "      <UpgradeVersion Property=\"MIXARLEGACY_${_legacy_major}_${_legacy_minor}\"\n"
        "        Maximum=\"255.255.255\" IncludeMaximum=\"yes\"\n"
        "        OnlyDetect=\"no\" MigrateFeatures=\"no\"/>\n"
        "    </Upgrade>\n"
      )
    endforeach()
  endforeach()
  unset(_legacy_major)
  unset(_legacy_minor)
  unset(_legacy_guid)

  # A Fragment is only linked when something references it, hence the marker
  # Property and the matching <PropertyRef> in WIX.template.
  set(MIXAR_LEGACY_UPGRADES_WXS "${CMAKE_BINARY_DIR}/mixar_legacy_upgrades.wxs")
  file(WRITE ${MIXAR_LEGACY_UPGRADES_WXS}
    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
    "<!-- Generated by build_files/cmake/packaging.cmake - do not edit. -->\n"
    "<Wix xmlns=\"http://schemas.microsoft.com/wix/2006/wi\">\n"
    "  <Fragment>\n"
    "    <Property Id=\"MIXAR_LEGACY_UPGRADE_MARKER\" Value=\"1\"/>\n"
    "${MIXAR_LEGACY_UPGRADE_XML}"
    "  </Fragment>\n"
    "</Wix>\n"
  )

  set(CPACK_WIX_TEMPLATE ${CMAKE_SOURCE_DIR}/release/windows/installer_wix/WIX.template)
  set(CPACK_WIX_UI_BANNER ${CMAKE_SOURCE_DIR}/release/windows/installer_wix/WIX_UI_BANNER.bmp)
  set(CPACK_WIX_UI_DIALOG ${CMAKE_SOURCE_DIR}/release/windows/installer_wix/WIX_UI_DIALOG.png)
  set(CPACK_WIX_EXTRA_SOURCES
    ${CMAKE_SOURCE_DIR}/release/windows/installer_wix/WixUI_Blender.wxs
    ${MIXAR_LEGACY_UPGRADES_WXS}
  )
  set(CPACK_WIX_UI_REF "WixUI_Blender")
  set(CPACK_WIX_LIGHT_EXTRA_FLAGS -dcl:medium)
endif()

set(CPACK_PACKAGE_EXECUTABLES "mixar-launcher" "Mixar ${MAJOR_VERSION}.${MINOR_VERSION}")
set(CPACK_CREATE_DESKTOP_LINKS "mixar-launcher" "Mixar ${MAJOR_VERSION}.${MINOR_VERSION}")

include(CPack)

# Target for build_archive.py script, to automatically pass along
# version, revision, platform, build directory
function(add_package_archive packagename extension)
  set(build_archive python ${CMAKE_SOURCE_DIR}/build_files/package_spec/build_archive.py)
  set(package_output ${CMAKE_BINARY_DIR}/release/${packagename}.${extension})

  add_custom_target(package_archive DEPENDS ${package_output})

  add_custom_command(
    OUTPUT ${package_output}
    COMMAND ${build_archive} ${packagename} ${extension} bin release
    WORKING_DIRECTORY ${CMAKE_BINARY_DIR}
  )
endfunction()

if(APPLE)
  add_package_archive(
    "${PROJECT_NAME}-${BLENDER_VERSION}-${BUILD_REV}-OSX-${CMAKE_OSX_ARCHITECTURES}"
    "zip"
  )
elseif(UNIX)
  # platform name could be tweaked, to include glibc, and ensure processor is correct (i386 vs i686)
  string(TOLOWER ${CMAKE_SYSTEM_NAME} PACKAGE_SYSTEM_NAME)

  add_package_archive(
    "${PROJECT_NAME}-${BLENDER_VERSION}-${BUILD_REV}-${PACKAGE_SYSTEM_NAME}-${CMAKE_SYSTEM_PROCESSOR}"
    "tar.xz"
  )
endif()

unset(MAJOR_VERSION)
unset(MINOR_VERSION)
unset(PATCH_VERSION)

unset(BUILD_REV)
