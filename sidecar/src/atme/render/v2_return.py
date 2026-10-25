"""Exact retained-board observation shared by replay and frame validation."""

from __future__ import annotations

from atme.render.v2_hierarchy import HierarchySnapshot
from atme.render.v2_hierarchy_replay import completed_hierarchy_basis


class UnsupportedReturn(ValueError):
    """A return would invent or reset retained board history."""


def validate_return_sample(resolved, hierarchy, frames, versions):
    """Check one captured local pose without mutating it or replaying another ledger."""
    action = resolved.action
    owned = {key for key, frame in frames.items() if frame.board_id == action.destination_board_id}
    if ({key: frames[key].state for key in owned} != action.expected_object_states
            or {key: versions[key] for key in owned} != action.expected_object_state_versions):
        raise UnsupportedReturn(f"return_board {action.action_id} changes retained board state")
    receipt = resolved.return_hierarchy_receipt
    if receipt is None:
        return
    board_hierarchy = HierarchySnapshot(tuple(node for node in hierarchy.nodes
                                              if node.board_id == action.destination_board_id))
    sampled_basis = completed_hierarchy_basis(board_hierarchy, {key: frames[key] for key in owned})
    if (receipt.action_id != action.action_id
            or receipt.destination_board_id != action.destination_board_id
            or receipt.destination_activation_id != action.destination_activation_id
            or receipt.hierarchy_basis != sampled_basis
            or receipt.hierarchy_basis_sha256 != sampled_basis.checksum()):
        raise UnsupportedReturn(f"return_board {action.action_id} changes retained board hierarchy")
