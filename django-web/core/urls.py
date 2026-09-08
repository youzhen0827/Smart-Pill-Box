from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("register/", views.register, name="register"),
    path("android-name/", views.android_name_settings, name="android_name_settings"),
    path("reminders/new/", views.reminder_create, name="reminder_create"),
    path("reminders/<int:record_id>/edit/", views.reminder_edit, name="reminder_edit"),
    path("reminders/<int:record_id>/taken/", views.reminder_taken, name="reminder_taken"),
    path("reminders/<int:record_id>/delete/", views.reminder_delete, name="reminder_delete"),
    path("schedules/", views.schedules, name="schedules"),
    path("schedules/new/", views.schedule_create, name="schedule_create"),
    path("schedules/<int:schedule_id>/edit/", views.schedule_edit, name="schedule_edit"),
    path("schedules/<int:schedule_id>/delete/", views.schedule_delete, name="schedule_delete"),
    path("elders/new/", views.elder_create, name="elder_create"),
    path("drugs/new/", views.drug_create, name="drug_create"),
    path("drugs/search-options/", views.drug_search_options, name="drug_search_options"),
    path("datasets/", views.dataset_center, name="dataset_center"),
    path("datasets/documents/<int:document_id>/", views.dataset_document, name="dataset_document"),
    path("qa/", views.qa_center, name="qa_center"),
    path("agent/", views.agent_center, name="agent_center"),
    path("agent/run/", views.run_agent_now, name="run_agent_now"),
    path("agent/sensor-test/", views.simulate_sensor_event, name="simulate_sensor_event"),
    # Versioned API
    path("api/v1/health/", views.api_health, name="api_health"),
    path("api/v1/reminders/", views.api_reminders, name="api_reminders"),
    path("api/v1/reminders/<int:record_id>/taken/", views.api_reminder_taken, name="api_reminder_taken"),
    path("api/v1/reminders/<int:record_id>/delete/", views.api_reminder_delete, name="api_reminder_delete"),
    path("api/v1/schedules/", views.api_schedules, name="api_schedules"),
    path("api/v1/schedules/<int:schedule_id>/", views.api_schedule_detail, name="api_schedule_detail"),
    path("api/v1/schedules/<int:schedule_id>/delete/", views.api_schedule_delete, name="api_schedule_delete"),
    path("api/v1/sensors/events/", views.api_sensor_event, name="api_sensor_event"),
    path("api/v1/qa/ask/", views.api_qa_ask, name="api_qa_ask"),
    path("api/v1/agent/interventions/", views.api_interventions, name="api_interventions"),
    path(
        "api/v1/agent/interventions/<int:intervention_id>/state/",
        views.api_intervention_state,
        name="api_intervention_state",
    ),
    path("api/v1/drugs/", views.api_drug_search, name="api_drug_search"),
    # Legacy Android compatibility
    path("upload/", views.upload_reminder, name="upload_reminder"),
    path("confirm/<int:record_id>/", views.confirm_taken, name="confirm_taken"),
]
