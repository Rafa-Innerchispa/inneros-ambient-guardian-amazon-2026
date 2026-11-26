"""Load the versioned Atlas extension, then start the unchanged canonical MCP."""
import importlib.util
from pathlib import Path
import runpy
import sys

PLATFORM=Path('/home/rlopez/inneros/inneros_core/platform')

def register_extension():
    if str(PLATFORM) not in sys.path:sys.path.insert(0,str(PLATFORM))
    from inneros_core_runtime import capability_gateway
    source=Path(__file__).with_name('capability_gateway_lighting.py')
    spec=importlib.util.spec_from_file_location('atlas_owner_lighting_extension',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.register_lighting_capabilities(capability_gateway.register_capability)

if __name__=='__main__':
    register_extension()
    runpy.run_path(str(PLATFORM/'scripts/run_mcp_runtime.py'),run_name='__main__')
