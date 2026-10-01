# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

.PHONY: init build clean_build install run i18n_update i18n_check

init:
	./scripts/unix/init.sh

build:
	./scripts/unix/build.sh

clean_build:
	./scripts/unix/build_clean.sh

install:
	./scripts/unix/install.sh

# Interface translations (see scripts/i18n): re-extract the UI strings into
# mixar.pot, merge it into every language catalog, re-derive sr_RS@latin and
# en_GB, then validate placeholders and report per-language coverage.
i18n_update:
	python3 scripts/i18n/extract_messages.py
	python3 scripts/i18n/update_catalogs.py
	python3 scripts/i18n/derive_catalogs.py
	python3 scripts/i18n/check_catalogs.py --quiet

i18n_check:
	python3 scripts/i18n/extract_messages.py --check
	python3 scripts/i18n/check_catalogs.py

# Run the built Mixar app.
#   make run           -> uses ./build/Dev
#   make run Prod      -> uses ./build/Prod
#   make run Dev_uat_6 -> uses ./build/Dev_uat_6
run:
	@./scripts/unix/run.sh $(filter-out $@,$(MAKECMDGOALS))

# Swallow extra goals (the build-folder name) so make doesn't error on them.
%:
	@: