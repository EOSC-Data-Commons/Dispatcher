import pytest
from rocrate.rocrate import ROCrate
from app.vres.base_vre import vre_factory
from app.vres.binder import VREBinder
from app.vres.sciencemesh import VREScienceMesh
from app.vres.galaxy import VREGalaxy
from app.vres.oscar import VREOSCAR


def test_factory_creates_sciencemesh_vre(sciencemesh_rocrate):
    vre = vre_factory(
        crate=sciencemesh_rocrate, token="test-token", request_id=0, update_state=None
    )
    assert isinstance(vre, VREScienceMesh)


def test_factory_creates_binder_vre(dummy_binder_crate):
    vre = vre_factory(
        crate=dummy_binder_crate, token="test-token", request_id=0, update_state=None
    )
    assert isinstance(vre, VREBinder)


def test_factory_creates_galaxy_vre(dummy_galaxy_crate):
    vre = vre_factory(
        crate=dummy_galaxy_crate, token="test-token", request_id=0, update_state=None
    )
    assert isinstance(vre, VREGalaxy)


def test_factory_creates_oscar_vre(dummy_oscar_crate):
    vre = vre_factory(
        crate=dummy_oscar_crate, token="test-token", request_id=0, update_state=None
    )
    assert isinstance(vre, VREOSCAR)


def test_factory_errors_on_unkown_vre_type(dummy_crate_with_unkown_vre_type):
    with pytest.raises(ValueError):
        vre_factory(
            crate=dummy_crate_with_unkown_vre_type,
            token="test-token",
            request_id=0,
            update_state=None,
        )
