.PHONY: clean
clean:
	rm -rf bundled dist node_modules

# The same sources the parent tracks: without them this copy goes stale silently, and the
# parent's own rebuild never reaches us.
SERVER_SOURCES := $(shell find ../../src -name '*.py' -o -name 'py.typed')

# The tree itself is built once in ../; vsce can only package from this directory, so copy it in.
bundled/libs/.installed: ../Makefile ../../uv.lock ../../pyproject.toml $(SERVER_SOURCES)
	$(MAKE) -C .. bundled/libs/.installed
	mkdir -p bundled && rm -rf bundled/libs && cp -R ../bundled/libs bundled/libs
	touch $@
