.PHONY: clean
clean:
	rm -rf bundled dist node_modules

# Pure-Python runtime closure. PyYAML's C parser sits behind a try/except ImportError, so
# deleting its .so leaves the pure-Python parser working.
bundled/libs/.installed: ../../uv.lock ../../pyproject.toml
	rm -rf bundled/libs
	cd ../.. && uv export --no-dev --no-emit-project --locked -o editors/code/requirements.txt
	uv pip install --target bundled/libs --no-installer-metadata -r requirements.txt
	cd ../.. && uv pip install --target editors/code/bundled/libs --no-deps .
	find bundled/libs \( -name '*.so' -o -name '*.pyd' -o -name '*.dylib' \) -delete
	python3 -c "import sys; sys.path.insert(0, 'bundled/libs'); import yaml, pygls.lsp.server, optics_framework_lsp.cli; assert not yaml.__with_libyaml__"
	touch $@
