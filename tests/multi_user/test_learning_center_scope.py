from __future__ import annotations

from deeptutor.services.learning_center import get_learning_center_repository


def test_learning_center_repository_is_scoped_per_current_user(as_user, mu_isolated_root) -> None:
    with as_user("u_alice"):
        alice = get_learning_center_repository()
        alice.create_project(project_id="alice-project", name="Alice course", kind="course")
    with as_user("u_bob"):
        bob = get_learning_center_repository()
        assert bob.db_path != alice.db_path
        assert bob.list_projects() == []
        bob.create_project(project_id="bob-project", name="Bob course", kind="course")
    with as_user("u_alice"):
        assert [project["id"] for project in get_learning_center_repository().list_projects()] == ["alice-project"]

    expected_root = (mu_isolated_root / "data" / "users")
    assert str(alice.db_path).startswith(str(expected_root))
    assert str(bob.db_path).startswith(str(expected_root))
