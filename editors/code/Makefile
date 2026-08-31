.PHONY: clean
clean:
	rm -rf bundled dist node_modules

# The tree itself is built once in ../; vsce can only package from this directory, so copy it in.
bundled/libs/.installed: ../Makefile ../../uv.lock ../../pyproject.toml
	$(MAKE) -C .. bundled/libs/.installed
	mkdir -p bundled && rm -rf bundled/libs && cp -R ../bundled/libs bundled/libs
	touch $@
