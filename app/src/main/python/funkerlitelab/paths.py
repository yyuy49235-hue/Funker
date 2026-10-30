"""Path validation. Uses resolved paths + Path.is_relative_to, never string prefixes."""
from pathlib import Path


class PathError(Exception):
    def __init__(self, code, message):
        super().__init__(f"{code}: {message}")
        self.code = code


def _inside(child: Path, parent: Path) -> bool:
    return child == parent or child.is_relative_to(parent)


def validate_roots(source, output=None, workspace=None):
    """Return resolved (source, output, workspace). Raises PathError on any unsafe layout."""
    src = Path(source).expanduser().resolve()
    if not src.is_dir():
        raise PathError("SOURCE_MISSING", f"source is not an accessible directory: {src}")
    out = Path(output).expanduser().resolve() if output else None
    ws = Path(workspace).expanduser().resolve() if workspace else None
    if out is not None:
        if _inside(out, src) or _inside(src, out):
            raise PathError("OVERLAP", "output and source overlap")
        if out.exists():
            raise PathError("DESTINATION_EXISTS",
                            f"destination already exists and will not be touched: {out}")
        if not out.parent.is_dir():
            raise PathError("DEST_PARENT_MISSING", f"parent of destination missing: {out.parent}")
    if ws is not None:
        if _inside(ws, src) or _inside(src, ws):
            raise PathError("WORKSPACE_OVERLAP", "workspace must be separate from the source")
        if out is not None and (_inside(ws, out) or _inside(out, ws)):
            raise PathError("WORKSPACE_OVERLAP", "workspace must be separate from the output")
    return src, out, ws
