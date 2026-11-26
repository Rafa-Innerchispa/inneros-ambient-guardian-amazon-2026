import ast
from pathlib import Path

def test_extension_is_loaded_before_starting_canonical_runtime():
    source=Path(__file__).parents[1]/'integrations/mcp_small/run_lighting_mcp.py'
    tree=ast.parse(source.read_text())
    main=next(n for n in tree.body if isinstance(n,ast.If))
    assert isinstance(main.body[0],ast.Expr)
    assert main.body[0].value.func.id=='register_extension'
    assert main.body[1].value.func.attr=='run_path'
    assert 'capability_gateway.py' not in source.read_text(), 'Launcher must not rewrite managed core files'
