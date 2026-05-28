import pytest
from app.vres.base_vre import vre_factory
from app.vres.binder import VREBinder
from app.vres.sciencemesh import VREScienceMesh
from app.vres.galaxy import VREGalaxy
from app.vres.oscar import VREOSCAR
from vre_rocrate import RequestPackage, WorkflowDescriptor
from vre_rocrate import (
    BINDER_PROGRAMMING_LANGUAGE,
    SCIENCEMESH_PROGRAMMING_LANGUAGE,
    GALAXY_PROGRAMMING_LANGUAGE,
    OSCAR_PROGRAMMING_LANGUAGE,
)


def _make_package(lang_id: str) -> RequestPackage:
    return RequestPackage(
        vre_type=lang_id,
        programming_language=lang_id,
        workflow=WorkflowDescriptor(id="#wf", type="SoftwareSourceCode"),
        raw_crate={},
    )


def test_factory_creates_sciencemesh_vre():
    vre = vre_factory(
        token="test-token",
        request_id=0,
        update_state=None,
        request_package=_make_package(SCIENCEMESH_PROGRAMMING_LANGUAGE),
    )
    assert isinstance(vre, VREScienceMesh)


def test_factory_creates_binder_vre():
    vre = vre_factory(
        token="test-token",
        request_id=0,
        update_state=None,
        request_package=_make_package(BINDER_PROGRAMMING_LANGUAGE),
    )
    assert isinstance(vre, VREBinder)


def test_factory_creates_galaxy_vre():
    vre = vre_factory(
        token="test-token",
        request_id=0,
        update_state=None,
        request_package=_make_package(GALAXY_PROGRAMMING_LANGUAGE),
    )
    assert isinstance(vre, VREGalaxy)


def test_factory_creates_oscar_vre():
    vre = vre_factory(
        token="test-token",
        request_id=0,
        update_state=None,
        request_package=_make_package(OSCAR_PROGRAMMING_LANGUAGE),
    )
    assert isinstance(vre, VREOSCAR)


def test_factory_errors_on_unkown_vre_type():
    with pytest.raises(ValueError):
        vre_factory(
            token="test-token",
            request_id=0,
            update_state=None,
            request_package=_make_package("random programming language"),
        )
