.PHONY: clean
clean:
	rm -rf bundled requirements.txt

# Pure-Python runtime closure, shared by every editor client. PyYAML's C parser sits behind a
# try/except ImportError, so deleting its .so leaves the pure-Python parser working — which is
# what keeps this tree platform-independent.
SERVER_SOURCES := $(shell find ../src -name '*.py' -o -name 'py.typed')

# The server's own sources count: without them, editing server.py leaves every client
# packaging the previous build.
bundled/libs/.installed: ../uv.lock ../pyproject.toml $(SERVER_SOURCES)
	rm -rf bundled/libs
	cd .. && uv export --no-dev --no-emit-project --locked -o editors/requirements.txt
	uv pip install --target bundled/libs --no-installer-metadata -r requirements.txt
	cd .. && uv pip install --target editors/bundled/libs --no-deps .
	find bundled/libs \( -name '*.so' -o -name '*.pyd' -o -name '*.dylib' \) -delete
	# Bytecode for this machine's interpreter is dead weight for a user on another one, and the
	# console script is unreachable anyway: every client launches with `-m`.
	find bundled/libs -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf bundled/libs/bin
	# -B so the check does not put __pycache__ straight back.
	python3 -B -c "import sys; sys.path.insert(0, 'bundled/libs'); import yaml, pygls.lsp.server, optics_framework_lsp.cli; assert not yaml.__with_libyaml__"
	touch $@
