# tests/rehome/test_detect.py
from dataclasses import dataclass

from brainpalace_server.rehome.detect import MoveInfo, detect_move, prefix_swap


@dataclass
class _Id:
    indexed_root: str


def test_prefix_swap_component_boundary():
    # in-root path swapped
    assert (
        prefix_swap("/old/root/src/a.py", "/old/root", "/new/home")
        == "/new/home/src/a.py"
    )
    # exact root swapped
    assert prefix_swap("/old/root", "/old/root", "/new/home") == "/new/home"
    # sibling that merely shares a string prefix is NOT swapped (component-wise)
    assert (
        prefix_swap("/old/rootstuff/a", "/old/root", "/new/home") == "/old/rootstuff/a"
    )
    # out-of-root (external folder) left verbatim
    assert (
        prefix_swap("/somewhere/else/a", "/old/root", "/new/home")
        == "/somewhere/else/a"
    )


def test_detect_move_returns_none_when_unmoved(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    assert detect_move(_Id(indexed_root=str(root)), root) is None


def test_detect_move_detects_relocation(tmp_path):
    old = tmp_path / "old" / "proj"
    old.mkdir(parents=True)
    new = tmp_path / "new" / "proj"
    new.mkdir(parents=True)
    old.rmdir()  # simulate: old location no longer exists after the move
    info = detect_move(_Id(indexed_root=str(old)), new)
    assert isinstance(info, MoveInfo)
    assert info.nested is False


def test_detect_move_flags_nested(tmp_path):
    old = tmp_path / "a" / "b"
    old.mkdir(parents=True)
    new = tmp_path / "a" / "b" / "c"
    new.mkdir(parents=True)
    info = detect_move(_Id(indexed_root=str(old)), new)
    assert info is not None and info.nested is True


def test_detect_move_symlink_same_inode_is_no_move(tmp_path):
    real = tmp_path / "proj"
    real.mkdir()
    link = tmp_path / "proj_link"
    link.symlink_to(real)
    # indexed at the symlinked path, now booting at the real path -> same inode
    assert detect_move(_Id(indexed_root=str(link)), real) is None
