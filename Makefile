# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

.PHONY: init build clean_build install

init:
	./scripts/unix/init.sh

build:
	./scripts/unix/build.sh

clean_build:
	./scripts/unix/build_clean.sh

install:
	./scripts/unix/install.sh