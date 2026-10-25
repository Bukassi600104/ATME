"""Original media adapters do not substitute unsupported construction modes."""

import pytest
from test_v2_media_decode import (
    encoded_vfr as encoded_vfr,  # noqa: PLC0414 -- pytest fixture re-export
)
from test_v2_media_runtime import runtime_documents

from atme.project_assets import VerifiedMediaBytes
from atme.render.v2_split_paint import (
    _freeze_verified_split_asset,
    _split_adapter,
    _split_primitive_paint,
    _VerifiedSplitAssetBytes,
    verify_split_paint_inputs,
)
from atme.store.contracts_v2 import (
    ExecutableLayoutV2,
    ResolvedAsset,
    SplitAssetPin,
)


@pytest.mark.parametrize("kind", ["video", "presenter", "screen_recording"])
def test_checked_moving_media_resource_has_only_faithful_split_construction(kind, encoded_vfr):
    document, timeline, _ = runtime_documents(encoded_vfr, kind=kind)
    layout = ExecutableLayoutV2.model_validate(document)
    asset = ResolvedAsset.model_validate(timeline["resolved_assets"][0])
    pin = SplitAssetPin(asset_id=asset.asset_id, revision=asset.revision,
        resource_uri=asset.managed_ref, checksum_sha256=asset.checksum_sha256)
    verified = VerifiedMediaBytes(asset.asset_id, asset.revision, encoded_vfr,
        asset.checksum_sha256, asset.width, asset.height, asset.media_stream.model_dump_json())
    frozen = _freeze_verified_split_asset(asset, pin, verified, layout=layout)
    # Prove the resource carrier succeeds first: a resource-validation failure
    # must not stand in for the construction-mode boundary.
    inputs = verify_split_paint_inputs(layout, _VerifiedSplitAssetBytes((frozen,)))
    assert inputs.project_assets[0].payload == encoded_vfr
    owner = layout.objects[2]
    assert _split_adapter(owner).family == "moving media"
    for mode in ("reveal", "enter"):
        assert _split_primitive_paint(owner, mode).family == "moving media"
    for mode in ("draw", "write"):
        with pytest.raises(ValueError, match=f"Split {mode} is incompatible with moving media construction"):
            _split_primitive_paint(owner, mode)
