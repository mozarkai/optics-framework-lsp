import * as assert from 'assert';

import { renderConfig } from '../mcp';

// The config is the part most likely to break on an mcpls upgrade, and mcpls refuses to start
// on an unknown key rather than warning — so a wrong shape means a silently dead MCP server.
suite('mcpls config', () => {
  const launch = {
    command: '/usr/bin/python3',
    args: ['-S', '-m', 'optics_framework_lsp'],
    options: { env: { PYTHONPATH: '/ext/bundled/libs' } },
  };

  test('nests language_extensions under workspace, where mcpls accepts it', () => {
    // At the top level this is an unknown field and mcpls exits before serving anything.
    assert.match(renderConfig(['/w'], launch), /^\[\[workspace\.language_extensions\]\]$/m);
  });

  test('launches the server the way the editor does', () => {
    const config = renderConfig(['/w'], launch);
    assert.match(config, /^command = "\/usr\/bin\/python3"$/m);
    assert.match(config, /^args = \["-S", "-m", "optics_framework_lsp"\]$/m);
    assert.match(config, /^env = \{ PYTHONPATH = "\/ext\/bundled\/libs" \}$/m);
  });

  test('escapes a windows path', () => {
    // TOML basic strings take the same escapes as JSON, so a backslash must be doubled or
    // mcpls reads C:\U... as an invalid unicode escape.
    const config = renderConfig(['C:\\Users\\qa\\suite'], launch);
    assert.match(config, /^roots = \["C:\\\\Users\\\\qa\\\\suite"\]$/m);
  });

  test('lists every folder of a multi-root workspace', () => {
    assert.match(renderConfig(['/a', '/b'], launch), /^roots = \["\/a", "\/b"\]$/m);
  });
});
