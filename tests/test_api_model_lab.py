# tests/test_api_model_lab.py

import pytest
from unittest.mock import patch, MagicMock

from api import crud, models

# It is assumed that you have an authenticated_client fixture in conftest.py
# which provides an httpx.AsyncClient with a valid authentication token.


@pytest.mark.anyio
async def test_model_lab_full_workflow(
    pro_user_client, db_session, mocker, pro_user: models.User
):
    """
    Tests the full "happy path" of a user in the Model Laboratory.
    """
    # --- Step 1: Creating a dataset generation task ---
    dataset_payload = {
        "name": "My First Dataset",
        "symbols": ["BTCUSDT"],
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-02-01T00:00:00Z",
        "feature_data_types": ["kline_1m"],
        "target_variable": "Future Price > 1%",
    }

    mock_celery_task = MagicMock()
    mock_celery_task.id = "celery-task-id-dataset-123"

    with patch(
        "api.depthsight_api.generate_dataset_task.apply_async",
        return_value=mock_celery_task,
    ) as mock_apply_async:
        response = await pro_user_client.post(
            "/api/v1/model-lab/datasets", json=dataset_payload
        )

    assert response.status_code == 202
    mock_apply_async.assert_called_once()

    dataset_run_data = response.json()
    assert dataset_run_data["name"] == "My First Dataset"
    assert dataset_run_data["status"] == "QUEUED"
    assert dataset_run_data["celery_task_id"] == mock_celery_task.id
    dataset_run_id = dataset_run_data["id"]

    # --- Step 2: Checking the status and list of datasets ---
    response = await pro_user_client.get(f"/api/v1/model-lab/datasets/{dataset_run_id}")
    assert response.status_code == 200
    assert response.json()["id"] == dataset_run_id

    response = await pro_user_client.get("/api/v1/model-lab/datasets")
    assert response.status_code == 200
    assert len(response.json()) >= 1
    assert any(d["id"] == dataset_run_id for d in response.json())

    # --- Step 3: Attempting training on an unready dataset (should fail) ---
    train_payload_fail = {
        "dataset_id": dataset_run_id,
        "model_type": "River HoeffdingTree",
    }
    response = await pro_user_client.post(
        "/api/v1/model-lab/train", json=train_payload_fail
    )
    assert response.status_code == 400
    error_detail_json = response.json()
    assert "error" in error_detail_json
    error_detail = error_detail_json["error"]
    assert error_detail is not None
    error_detail = error_detail.lower()
    assert "not completed" in error_detail or "is not ready" in error_detail

    # --- Step 4: Simulating the completion of the dataset generation task ---
    db_run = await crud.get_dataset_run(
        db_session, user_id=pro_user.id, run_id=dataset_run_id
    )
    assert db_run is not None, (
        "DatasetRun should have been found in the DB after creation."
    )
    db_run.status = "COMPLETED"
    db_run.file_path = "/data/datasets/fake_dataset.parquet"
    await db_session.commit()

    # --- Step 5: Starting training on a ready dataset ---
    train_payload_success = {
        "dataset_id": dataset_run_id,
        "model_type": "River HoeffdingTree",
        "hyperparameters": {"grace_period": 200},
    }

    mock_celery_task.id = "celery-task-id-train-456"
    with patch(
        "api.depthsight_api.train_model_task.apply_async", return_value=mock_celery_task
    ) as mock_train_apply_async:
        response = await pro_user_client.post(
            "/api/v1/model-lab/train", json=train_payload_success
        )

    assert response.status_code == 202
    mock_train_apply_async.assert_called_once()

    training_run_data = response.json()
    assert training_run_data["dataset_id"] == dataset_run_id
    assert training_run_data["status"] == "QUEUED"
    training_run_id = training_run_data["id"]

    # --- Step 6: Checking the status and list of trained models ---
    response = await pro_user_client.get(f"/api/v1/model-lab/train/{training_run_id}")
    assert response.status_code == 200
    assert response.json()["id"] == training_run_id

    response = await pro_user_client.get("/api/v1/model-lab/train")
    assert response.status_code == 200
    assert len(response.json()) >= 1
    assert any(d["id"] == training_run_id for d in response.json())
