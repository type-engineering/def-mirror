# Handgriffe für dieses Repo. `make` ohne Ziel zeigt die Liste.
#
# Besonderheit hier: Das Repo hat einen zweiten Autor, der nie schläft. Der
# Workflow `mirror.yml` committet täglich den neuen Stand, der lokale Klon
# hinkt also fast immer hinterher. Ein blindes `git push` scheitert dann mit
# "non-fast-forward" — und die naheliegende Antwort darauf wäre ein
# `--force`, das genau die öffentliche Historie zerstört, auf der laut
# ADR 0006 das Vertrauensmodell steht.

REMOTE ?= origin
BRANCH ?= main

.DEFAULT_GOAL := help
.PHONY: help backend test

help:
	@echo "make backend  — lokale Commits auf den Remote-Stand rebasen und pushen"
	@echo "make test     — Regressionstest des Ernters (ohne Netz, gegen die Fixture)"

# Derselbe Test, den der Workflow als Torwächter vor dem Ernten laufen lässt.
# Braucht kein Netz und fasst die echte Quellseite nicht an.
test:
	python3 tools/test_harvest.py

# Rebase auf den Remote-Stand, dann push. Kein Merge: Die täglichen Stände
# sollen eine gerade Linie bleiben, damit die Historie lesbar ist — sie ist
# hier Teil des Produkts, nicht nur Werkzeug.
#
# Die Prüfungen davor sind nicht Bürokratie, sondern jeweils ein Fehler, der
# sonst mitten im Rebase auffällt, wenn er teurer ist.
backend:
	@test -d .git || { echo "Kein Git-Repo — bist du im richtigen Verzeichnis?"; exit 1; }
	@if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ]; then \
	    echo "Es läuft bereits ein Rebase. Erst abschließen:"; \
	    echo "    git rebase --continue    # Konflikte gelöst"; \
	    echo "    git rebase --abort       # doch nicht"; \
	    exit 1; \
	fi
	@zweig=$$(git rev-parse --abbrev-ref HEAD); \
	if [ "$$zweig" != "$(BRANCH)" ]; then \
	    echo "Du bist auf '$$zweig', nicht auf '$(BRANCH)'."; \
	    echo "Absicht? Dann: make backend BRANCH=$$zweig"; \
	    exit 1; \
	fi
	@if [ -n "$$(git status --porcelain --untracked-files=no)" ]; then \
	    echo "Unfertige Änderungen im Arbeitsbaum — erst committen, dann backend:"; \
	    git status --short --untracked-files=no; \
	    exit 1; \
	fi
	@echo "→ hole $(REMOTE)/$(BRANCH)" >&2
	@git fetch --quiet $(REMOTE) $(BRANCH)
	@echo "→ rebase auf $(REMOTE)/$(BRANCH)" >&2
	@git rebase $(REMOTE)/$(BRANCH) || { \
	    echo ""; \
	    echo "Rebase steht — deine Änderung und der Mirror-Stand fassen dieselbe Datei an."; \
	    echo "Das ist ungewöhnlich: der Mirror schreibt nur defects.json,"; \
	    echo "defects.signed.json und defects-source.txt."; \
	    echo ""; \
	    echo "    git status               # was kollidiert"; \
	    echo "    git rebase --continue    # nach dem Lösen"; \
	    echo "    git rebase --abort       # zurück auf Anfang, nichts verloren"; \
	    exit 1; \
	}
	@if [ -z "$$(git log $(REMOTE)/$(BRANCH)..HEAD --oneline)" ]; then \
	    echo "✓ Nichts zu pushen — Stand ist schon der des Servers." >&2; \
	else \
	    echo "→ push:" >&2; \
	    git log $(REMOTE)/$(BRANCH)..HEAD --oneline | sed 's/^/     /' >&2; \
	    git push $(REMOTE) $(BRANCH); \
	fi
