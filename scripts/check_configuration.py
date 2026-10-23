"""Keep supported environment, recipe and command controls in both references."""
import ast,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def inventory():
    roles={}
    for role in ['api','segmentation-worker','qwen-worker','moss-worker','event-worker','vocal-worker','measurement-worker']:
        opts={}
        # Auxiliary download tools can have different fallbacks. Runtime app.py
        # wins deterministically, independent of filesystem directory ordering.
        paths=sorted((ROOT/'providers/speech'/role).glob('*.py'),key=lambda p:(p.name=='app.py',p.name))
        for n in [n for path in paths for n in ast.walk(ast.parse(path.read_text()))]:
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='getenv' and n.args and isinstance(n.args[0],ast.Constant):
                opts[n.args[0].value]=str(n.args[1].value) if len(n.args)>1 and isinstance(n.args[1],ast.Constant) else None
        roles[role]=dict(sorted(opts.items()))
    return roles

def environment_names():
    names=set()
    paths=list((ROOT/'sonovect').glob('*.py'))+list((ROOT/'providers/speech/shared').glob('*.py'))
    for path in paths:
        tree=ast.parse(path.read_text())
        literals={n.targets[0].id:n.value.value for n in ast.walk(tree)
                  if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)
                  and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)}
        for n in ast.walk(tree):
            if not (isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='getenv' and n.args):
                continue
            arg=n.args[0]
            if isinstance(arg,ast.Constant) and isinstance(arg.value,str):names.add(arg.value)
            elif (isinstance(arg,ast.BinOp) and isinstance(arg.op,ast.Add) and isinstance(arg.left,ast.Name)
                  and arg.left.id in literals and isinstance(arg.right,ast.Constant)):
                names.add(literals[arg.left.id]+arg.right.value)
    return names
if __name__=='__main__':
    path=ROOT/'docs/runtime-options.json'
    if '--write' in sys.argv:path.write_text(json.dumps(inventory(),indent=2)+'\n')
    assert json.loads(path.read_text())==inventory(),'run python scripts/check_configuration.py --write'
    for language in ['configuration.md','configuration.zh-CN.md']:
        text=(ROOT/'docs'/language).read_text()
        missing={key for options in inventory().values() for key in options if key not in text}
        assert not missing,language+': undocumented environment options: '+str(missing)
        assert all(name in text for name in environment_names()),language+': undocumented core/shared environment controls'
        compose_names={name for file in (ROOT/'deploy').glob('*.yml') for name in re.findall(r'\$\{([A-Z0-9_]+)',file.read_text())}
        assert not (compose_names-set(re.findall(r'\b[A-Z][A-Z0-9_]+\b',text))),language+': undocumented Compose controls'
        for file in ['sonovect/cli.py','sonovect/setup.py','sonovect/assets.py','scripts/prepare_deployment.py']:
            for node in ast.walk(ast.parse((ROOT/file).read_text())):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='add_argument':
                    flags=[arg.value for arg in node.args if isinstance(arg,ast.Constant) and isinstance(arg.value,str) and arg.value.startswith('--')]
                    assert all(flag in text for flag in flags),language+': undocumented flags in '+file
    print('Provider environment, Compose controls and CLI flags are documented in both languages')
