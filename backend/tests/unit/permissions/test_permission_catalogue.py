"""The permission dependency rules, and the promise that the catalogue stays honest.

The rule these protect is a safety one: granting an action may add *reading* rights, and must
never add a second action. A bug here would hand somebody a power nobody ticked.
"""

from app.modules.permissions.catalogue import (
    DESCRIPTIONS,
    EXPLICIT_DEPENDENCIES,
    dependencies_for,
    expand,
)
from app.modules.roles.seeds import SEED_PERMISSIONS

ALL_CODES = {seed.code for seed in SEED_PERMISSIONS}


class TestCatalogue:
    def test_every_seeded_permission_is_described(self):
        # The screen exists to be read. A permission with no sentence is the bug being fixed.
        missing = sorted(ALL_CODES - set(DESCRIPTIONS))
        assert missing == [], f"no description for: {missing}"

    def test_no_description_for_a_permission_that_does_not_exist(self):
        # A stale entry here is a description nobody will ever see, and a hint that a
        # permission was renamed without the catalogue following it.
        extra = sorted(set(DESCRIPTIONS) - ALL_CODES)
        assert extra == [], f"described but not seeded: {extra}"

    def test_declared_dependencies_all_exist(self):
        for code, required in EXPLICIT_DEPENDENCIES.items():
            assert code in ALL_CODES, f"{code} is not a real permission"
            for dependency in required:
                assert dependency in ALL_CODES, f"{code} depends on unknown {dependency}"


class TestDependencies:
    def test_an_action_implies_its_own_module_view(self):
        assert "users.view" in dependencies_for("users.create", ALL_CODES)
        assert "orders.view" in dependencies_for("orders.cancel", ALL_CODES)

    def test_a_view_implies_nothing_of_its_own_module(self):
        assert "users.view" not in dependencies_for("users.view", ALL_CODES)
        assert dependencies_for("dashboard.view", ALL_CODES) == ()

    def test_a_differently_named_read_is_still_found(self):
        # `authentication` has no `authentication.view`; its read is `view_sessions`.
        assert dependencies_for("authentication.revoke_sessions", ALL_CODES) == (
            "authentication.view_sessions",
        )

    def test_a_dependency_can_cross_modules(self):
        # Giving somebody a role means picking from the list of roles.
        assert "roles.view" in dependencies_for("users.assign_roles", ALL_CODES)
        assert "users.view" in dependencies_for("users.assign_roles", ALL_CODES)

    def test_unknown_dependencies_are_dropped_rather_than_granted(self):
        # A catalogue with the module read removed must not hand out a permission that is not
        # in it - the role could never use it and the matrix could never show it.
        shrunk = ALL_CODES - {"users.view"}
        assert "users.view" not in dependencies_for("users.create", shrunk)


class TestExpand:
    def test_ticking_one_action_brings_its_screen(self):
        assert expand({"users.create"}, ALL_CODES) == {"users.create", "users.view"}

    def test_dependencies_are_followed_all_the_way_down(self):
        # approve -> customer_documents.view -> customers.view
        result = expand({"customer_documents.approve"}, ALL_CODES)
        assert result == {
            "customer_documents.approve",
            "customer_documents.view",
            "customers.view",
        }

    def test_nothing_is_added_beyond_reads(self):
        # The promise: an action never pulls in another action. Every code added on top of
        # what was asked for must be a read.
        for code in sorted(ALL_CODES):
            added = expand({code}, ALL_CODES) - {code}
            for extra in added:
                action = extra.partition(".")[2]
                assert action.startswith("view"), f"{code} would also grant {extra}"

    def test_expanding_twice_changes_nothing(self):
        once = expand({"users.assign_roles", "orders.assign"}, ALL_CODES)
        assert expand(once, ALL_CODES) == once

    def test_an_empty_choice_stays_empty(self):
        assert expand(set(), ALL_CODES) == set()

    def test_every_catalogue_entry_expands_without_looping(self):
        # The fixed-point loop terminates for every real permission, including any future
        # entry somebody adds with a cycle in it.
        for code in ALL_CODES:
            assert code in expand({code}, ALL_CODES)
