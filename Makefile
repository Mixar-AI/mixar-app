# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

.PHONY: init build clean_build install run

init:
	./scripts/unix/init.sh

build:
	./scripts/unix/build.sh

clean_build:
	./scripts/unix/build_clean.sh

install:
	./scripts/unix/install.sh

# Run the built Mixar app.
#   make run           -> uses ./build/Dev
#   make run Prod      -> uses ./build/Prod
#   make run Dev_uat_6 -> uses ./build/Dev_uat_6
run:
	@./scripts/unix/run.sh $(filter-out $@,$(MAKECMDGOALS))

# Swallow extra goals (the build-folder name) so make doesn't error on them.
%:
	@: