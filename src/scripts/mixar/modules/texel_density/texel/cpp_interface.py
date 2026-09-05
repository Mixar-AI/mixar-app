# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

import ctypes
import os
import sys

# Effective-backend fallback state. Selecting 'CPP' without a loadable native
# library used to silently run the slow Python path; the availability probe
# below runs once per session and the fallback is logged once.
_tdcore_available = None
_cpp_fallback_warned = False


class TDCoreWrapper:
	def __init__(self):
		self.lib = self._load_library()
		if self.lib:
			self._bind_functions()

	def __del__(self):
		self._unload_library()

	def _load_library(self):
		if sys.platform.startswith("win"):
			lib_name = "tdcore.dll"
		elif sys.platform.startswith("linux"):
			lib_name = "libtdcore.so"
		elif sys.platform.startswith("darwin"):  # macOS
			lib_name = "libtdcore.dylib"
		else:
			return None

		addon_path = os.path.dirname(os.path.abspath(__file__))
		tdcore_path = os.path.join(addon_path, lib_name)

		if not os.path.isfile(tdcore_path):
			print(f"Library not found: {tdcore_path}. Will use python backend instead.")
			return None

		try:
			if sys.platform.startswith("win"):
				return ctypes.WinDLL(tdcore_path)  # Windows
			else:
				return ctypes.CDLL(tdcore_path)  # Linux/macOS
		except OSError as e:
			print(f"Failed to load library {tdcore_path}: {e}")
			return None

	def _bind_functions(self):
		self.lib.CalculateTDAreaArray.argtypes = [
			ctypes.POINTER(ctypes.c_float),  # UVs
			ctypes.c_int,  # UVs Count
			ctypes.POINTER(ctypes.c_float),  # Areas
			ctypes.POINTER(ctypes.c_int),  # Vertex Count by Polygon
			ctypes.c_int,  # Poly Count
			ctypes.c_float,  # Scale
			ctypes.c_int,  # Units
			ctypes.POINTER(ctypes.c_float)  # Results
		]

		self.lib.CalculateTDAreaArray.restype = None

		self.lib.ValueToColor.argtypes = [
			ctypes.POINTER(ctypes.c_float),  # Values
			ctypes.c_int,  # Values Count
			ctypes.c_float,  # Range Min
			ctypes.c_float,  # Range Max
			ctypes.POINTER(ctypes.c_float)  # Results
		]

		self.lib.ValueToColor.restype = None

	def _unload_library(self):
		if not self.lib or not hasattr(self.lib, '_handle'):
			return

		try:
			handle = ctypes.c_void_p(self.lib._handle)

			if sys.platform.startswith("win"):
				# Windows
				kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
				kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
				if not kernel32.FreeLibrary(handle):
					raise ctypes.WinError(ctypes.get_last_error())
			else:
				# Linux/Mac
				libc = ctypes.CDLL(None)
				libc.dlclose.argtypes = [ctypes.c_void_p]
				if libc.dlclose(handle) != 0:
					raise RuntimeError("Failed to dlclose library")
		except Exception as e:
			print(f"Warning: Library unload error: {str(e)}")
		finally:
			del self.lib
			self.lib = None


def tdcore_available():
	"""Probe once per session whether the native library can be loaded."""
	global _tdcore_available
	if _tdcore_available is None:
		probe = TDCoreWrapper()
		_tdcore_available = probe.lib is not None
		del probe
	return _tdcore_available


def resolve_calculation_backend(preferred_backend):
	"""Return the effective calculation backend.

	'CPP' requires the native tdcore library; when it cannot be loaded on this
	platform (e.g. macOS without libtdcore.dylib), fall back to the Python
	backend and log a one-time warning instead of silently running the slow
	path while the preference still says C++ (Fast).
	"""
	global _cpp_fallback_warned
	if preferred_backend != 'CPP':
		return preferred_backend

	if not tdcore_available():
		if not _cpp_fallback_warned:
			_cpp_fallback_warned = True
			print("[WARNING] Texel Density: native C++ backend (tdcore) is not available on this platform, using the Python backend instead")
		return 'PY'

	return 'CPP'