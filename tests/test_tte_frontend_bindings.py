from __future__ import annotations

from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _atlas_dev_root() -> Path:
    repo_root = _repo_root()
    direct_root = repo_root / "atlas-dev"
    if direct_root.exists():
        return direct_root

    raise FileNotFoundError("atlas-dev checkout not found under the current repo root")


def _atlas_dev_text(*relative_parts: str) -> str:
    return (_atlas_dev_root().joinpath(*relative_parts)).read_text()


def test_tte_manager_does_not_mix_if_and_with_on_same_element():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")

    forbidden_lines = [
        line.strip()
        for line in html.splitlines()
        if 'data-bind="' in line and "if:" in line and "with:" in line
    ]

    assert forbidden_lines == []


def test_tte_manager_renders_capability_signal_labels():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")

    assert "Capability Signals" in html
    assert "Current Fidelity" in html
    assert "artifact-capability-note" in html


def test_tte_manager_comments_out_artifact_review_mount_point():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")

    assert "<!--\n    <div data-bind=\"template: { name: 'tte-artifact-review-template' }\"></div>\n    -->" in html
    assert "<!-- ko if: shouldShowArtifactReview -->" not in html
    assert '<script type="text/html" id="tte-artifact-review-template">' in html


def test_tte_manager_renders_analysis_evaluation_labels():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "Analysis Method" in html
    assert "Matched Pairs" in html
    assert "Primary Execution Model" in html
    assert "Candidate Models" not in html
    assert "Execution PS Method" in html
    assert "Methods to Consider" not in html
    assert "Propensity Score Matching" in js
    assert "Propensity Score Stratification" in js
    assert "Inverse Probability Weighting" in js
    assert "Mahalanobis" in js
    assert "28-day Cumulative Mortality" in html
    assert "Love Plot" in html
    assert "analysisCumulativeMortalitySvg" in html
    assert "analysisLovePlotSvg" in html
    assert "renderAnalysisLinePlotSvg" in js
    assert "renderAnalysisLovePlotSvg" in js
    assert "getResultPlotByKey" in js
    assert "disabled: false" in js


def test_tte_manager_renders_analysis_diagnosis_facts_with_data_qualified_fields():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")

    assert "text: label || ''" not in html
    assert "visible: label && value" not in html
    assert "text: value || $data" not in html
    assert "text: $data.label || ''" in html
    assert "visible: $data.label && $data.value" in html
    assert "text: $data.value || $data" in html


def test_tte_manager_initializes_selected_tab_from_router_section():
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "this.selectedTabKey = ko.observable(params.section || 'specification');" not in js
    assert "this.selectedTabKey = ko.observable(routerParams.section || 'specification');" in js


def test_tte_manager_run_analysis_refreshes_study_and_opens_results_tab():
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert ".then(saved => this.evaluateAnalysisStrategyForMethod(null, { stage: 'final', silent: true })" not in js
    assert ".then(saved => TTEService.runAnalysis(saved.id))" in js
    assert ".then(response => this.refreshStudyAndArtifacts().then(() => {" in js
    assert "this.selectTab({ key: 'results' });" in js


def test_tte_manager_renders_analysis_run_completion_notice():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "analysisRunNotice = ko.observable(null);" in js
    assert "analysisRunNoticeCss = ko.pureComputed" in js
    assert "data-bind=\"visible: analysisRunNotice, css: analysisRunNoticeCss\"" in html


def test_tte_manager_uses_null_safe_analysis_result_helpers():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "formatAnalysisNumber" in js
    assert "formatAnalysisInterval" in js
    assert "formatAnalysisPValue" in js
    assert "analysisPValueClass" in js
    assert "results().hazardRatio.toFixed(2)" not in html
    assert "results().hrLower95.toFixed(2)" not in html
    assert "results().hrUpper95.toFixed(2)" not in html
    assert "results().pValue.toFixed(4)" not in html
    assert "results().pValue < 0.05" not in html
    assert "text: formatAnalysisNumber(results() && results().hazardRatio, 2, 'HR: ')" in html
    assert "text: formatAnalysisInterval(results())" in html
    assert "css: analysisPValueClass(results())" in html
    assert "text: formatAnalysisPValue(results() && results().pValue)" in html


def test_tte_frontend_recovers_process_eligibility_after_gateway_timeout():
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")
    service_js = _atlas_dev_text(
        "js", "pages", "target-trial-emulation", "services", "TTEService.js"
    )

    assert "getProcessEligibilityProgress" in service_js
    assert "Gateway timeout while waiting for the TTE backend." in service_js
    assert "waitForEligibilityProcessingCompletion(studyId)" in js
    assert "this.isGatewayTimeoutError(err)" in js
    assert "response && response.status === 'completed' && response.artifactId" in js


def test_tte_manager_uses_execution_plus_candidates_analysis_hierarchy():
    repo_root = Path(__file__).resolve().parents[2]
    html = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "tte-manager.html"
    ).read_text()
    js = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "tte-manager.js"
    ).read_text()

    assert "Analysis Recommendation" in html
    assert "Current run" in html
    assert "analysisExecutionSummary" in html
    assert "analysisExecutionStatusCopy" in html
    assert "analysisCandidateModels" not in html
    assert "analysisMethodRecommendations" not in html
    assert "Current diagnosis" in html
    assert "Why this method" in html
    assert "Why not the alternatives" in html
    assert "Proposed Parameters" in html
    assert "Manual Execution Setup" in html
    assert "Manual Propensity Score Strategy" in html
    assert "selectedPsStrategy" in html
    assert "optionsAfterRender: applyPsStrategyOptionState" in html
    assert "isCaliperExecutionActive" in html
    assert "isCaliperRelevant" in html
    assert "caliperHelperText" in html
    assert "tte-analysis-heading" in html
    assert "tte-analysis-inline-note" not in html
    assert "enable: isCaliperRelevant" in html
    assert "analysisExecutionSummary = ko.pureComputed" in js
    assert "analysisExecutionStatusCopy = ko.pureComputed" in js
    assert "analysisDraftRecommendationKey = ko.observable('');" in js
    assert "analysisRecommendationNotice = ko.observable('');" in js
    assert "maybeTriggerDraftAnalysisRecommendation()" in js
    assert "analysisCandidateModels = ko.pureComputed" not in js
    assert "psStrategyOptions" in js
    assert "selectedPsStrategy = ko.pureComputed" in js
    assert "applyPsStrategyOptionState" in js
    assert "mahalanobis" in js
    assert "analysisMethodRecommendations = ko.pureComputed" not in js
    assert "executionMethodStatusLabel = ko.pureComputed" not in js
    assert "isCaliperRelevant = ko.pureComputed" in js
    assert "caliperHelperText = ko.pureComputed" in js
    assert "analysisSupportNote = ko.pureComputed" not in js


def test_tte_manager_renders_report_preview_diagnostic_labels():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")

    assert "Preview Analysis Method" in html
    assert "Preview Matched Pairs" in html


def test_tte_manager_uses_results_and_report_tab_labels():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "{ key: 'results', title: 'Results', icon: 'bar-chart' }" in js
    assert "{ key: 'report', title: 'Report', icon: 'file-pdf-o' }" in js
    assert "{ key: 'results', title: 'Generation & Analysis', icon: 'bar-chart' }" not in js
    assert "{ key: 'report', title: 'Report Summary', icon: 'file-pdf-o' }" not in js
    assert "<i class=\"fa fa-file-text-o\"></i> Report" in html
    assert "Generate Report" in html
    assert "Generate Report Summary" not in html


def test_tte_manager_renders_report_style_analysis_summary_sections():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")

    assert "Research Question" in html
    assert "Key Finding" in html
    assert "Population" in html
    assert "Intervention" in html
    assert "Statistical Findings" in html


def test_tte_manager_limits_report_summary_payload_to_report_artifacts_and_normalizes_legacy_shapes():
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "artifact.kind !== 'report_summary'" in js
    assert "typeof summary === 'string'" in js
    assert "title: 'Report'" in js
    assert "text: summary.text || ''" in js


def test_tte_manager_renders_embedded_report_bundle_host_without_replacing_legacy_preview():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")
    adapter_js = _atlas_dev_text(
        "js", "pages", "target-trial-emulation", "components", "tte-report-bundle-adapter.js"
    )
    bridge_js = _atlas_dev_text(
        "js", "pages", "target-trial-emulation", "components", "tte-report-bundle-bridge.js"
    )

    assert "Embedded Report Preview" in html
    assert 'id="tte-report-bundle-host"' in html
    assert "reportBundleUsesLegacyPath" in html
    assert 'data-bind="visible: reportPreviewVisible"' in html
    assert "reportBundlePayload = ko.observable(null);" in js
    assert "reportBundleRenderError = ko.observable('');" in js
    assert "refreshReportBundlePayload()" in js
    assert "syncReportBundleMount()" in js
    assert "mode === 'webapi_generation'" in adapter_js
    assert "return null;" in adapter_js
    assert "TTEReportBundleBridgeBuilt" in bridge_js
    assert "require.toUrl('./tte-report-bundle-bridge-built.js')" in bridge_js


def test_tte_manager_uses_trial_first_specification_labels():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")

    assert "Preview Trial" in html
    assert "Import Trial" in html
    assert "Draft Generation" not in html
    assert "Generate Draft" not in html


def test_tte_manager_renders_specification_workflow_copy():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "Review Draft" not in html
    assert "Protocol Review" not in html
    assert "Canonical study state" not in html
    assert "Continue with Eligibility, Treatment, and Outcomes." not in html
    assert "Refine Study" not in html
    assert "tte-preview-inline" in html
    assert "Preview metadata loaded from ClinicalTrials.gov." in html
    assert "tte-preview-card" not in html
    assert "Importing trial" in js
    assert "Generating protocol draft" in js


def test_tte_manager_treats_import_as_draft_only_and_wires_seeded_cohort_generation_step():
    repo_root = Path(__file__).resolve().parents[2]
    html = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "tte-manager.html"
    ).read_text()
    js = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "tte-manager.js"
    ).read_text()

    assert "triggerSeededCohortGeneration" in js
    assert "canGenerateSeededCohorts" in js
    assert "hasResolvedCohortIds" in js
    assert "Generate Seeded Cohorts" in js
    assert "creates target, treatment, and outcome cohorts together" in js


def test_tte_manager_uses_seeded_materialization_copy_for_seeded_generation_artifacts():
    repo_root = Path(__file__).resolve().parents[2]
    html = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "tte-manager.html"
    ).read_text()
    js = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "tte-manager.js"
    ).read_text()

    assert "artifactReviewTitle" in js
    assert "artifactReviewIntro" in js
    assert "artifactReviewEmptyCopy" in js
    assert "first cohort-materialization step" in js
    assert "Generate Seeded Cohorts creates target, treatment, and outcome cohorts together" in js
    assert "text: artifactReviewTitle()" in html
    assert "text: artifactReviewIntro()" in html


def test_tte_manager_renders_hybrid_treatment_strategy_controls():
    repo_root = Path(__file__).resolve().parents[2]
    html = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "tte-manager.html"
    ).read_text()
    js = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "tte-manager.js"
    ).read_text()

    assert "Treatment Strategy" in html
    assert "Treatment vs Rest" in html
    assert "Explicit Comparator" in html
    assert "Add Arm" not in html
    assert "comparisonMode" in js
    assert "isTreatmentLocked" in js


def test_tte_manager_wires_treatment_cohort_picker_modal():
    repo_root = Path(__file__).resolve().parents[2]
    html = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "tte-manager.html"
    ).read_text()
    js = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "tte-manager.js"
    ).read_text()

    assert "cohort-definition-browser" in html
    assert "openTreatmentCohortModal" in js
    assert "applySelectedTreatmentCohort" in js
    assert "treatmentCohortModalOpen" in js


def test_tte_manager_wires_primary_outcome_manual_selection_path():
    repo_root = Path(__file__).resolve().parents[2]
    html = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "tte-manager.html"
    ).read_text()
    js = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "tte-manager.js"
    ).read_text()

    assert "selectPrimaryOutcome" in js
    assert 'data-bind="click: selectPrimaryOutcome, disable: isImportingTrial()"' in html
    assert "primaryOutcomeModalOpen" in js
    assert "applyPrimaryOutcomeSelection" in js
    assert "Select primary outcome cohort" in html
    assert "Apply Outcome Cohort" in html


def test_tte_manager_enforces_seeded_treatment_lock_in_handlers_and_button_binding():
    repo_root = Path(__file__).resolve().parents[2]
    html = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "tte-manager.html"
    ).read_text()
    js = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "tte-manager.js"
    ).read_text()

    assert "Seeded from NCT, locked" in html
    assert "click: function() { $parent.openTreatmentCohortModal(0); }, disable: $parent.isTreatmentLocked()" in html
    assert "if (armIndex === 0 && this.isTreatmentLocked())" in js
    assert "if (this.activeTreatmentArmIndex() === 0 && this.isTreatmentLocked())" in js


def test_tte_manager_uses_perceptible_import_progress_helper():
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "waitForPerceptibleImportProgress" in js
    assert "minimumImportProgressMs = 1400" in js


def test_tte_manager_renders_eligibility_matrix_banner_and_editable_import_copy():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "tte-eligibility-banner" in html
    assert "shouldShowEligibilityMatrixBanner" in html
    assert "eligibilityMatrixBannerState" in html
    assert "eligibilityMatrixBanner" in html
    assert "eligibilityMatrixPrimaryAction" in html
    assert "eligibilityMatrixSecondaryActions" in html
    assert "seededEligibilityStatusEyebrow = ko.pureComputed" in js
    assert "Trial Import In Progress" in js
    assert "Imported Criteria Ready" in js
    assert "seededEligibilityStatusMetaCopy = ko.pureComputed" in js
    assert "Rows stay editable before processing, validation, save, or execution." in js


def test_tte_manager_hides_empty_artifact_review_scaffolding():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")

    assert "shouldShowArtifactReview" in html


def test_tte_manager_tracks_seeded_import_success_before_showing_handoff():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "hasSuccessfulSeededImport" in js
    assert "hasAttemptedSeededImport" in js
    assert "shouldShowImportHandoff" in js
    assert "getLatestAppliedGenerateFromNctArtifact(this.artifacts())" in js
    assert "artifact.capability === 'generate_from_nct' && !!artifact.appliedAt" not in js


def test_tte_manager_rehydrates_seeded_guidance_from_applied_import_artifacts():
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "getLatestAppliedGenerateFromNctArtifact" in js
    assert "payload.meta.nctId" in js
    assert "this.studyVersion = ko.observable(null);" in js
    assert "const currentStudyVersion = this.studyVersion();" in js
    assert "Number(artifact.studyVersion) >= Number(currentStudyVersion) - 1" in js
    assert "Number(artifact.studyVersion) <= Number(currentStudyVersion)" in js


def test_tte_manager_ignores_stale_applied_import_artifacts_from_older_study_versions():
    repo_root = Path(__file__).resolve().parents[2]
    js = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "tte-manager.js"
    ).read_text()

    assert "const currentStudyVersion = this.studyVersion();" in js
    assert "Number(artifact.studyVersion) >= Number(currentStudyVersion) - 1" in js
    assert "Number(artifact.studyVersion) <= Number(currentStudyVersion)" in js


def test_tte_manager_disables_specification_editor_during_import():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert 'click: startFromSelectedTrial, enable: canStartFromSelectedTrial' in html
    assert 'disable: isImportingTrial() || isFetchingPreview() || !nctId().trim()' in html
    assert "!this.isImportingTrial()" in js


def test_tte_manager_renders_next_required_action_strip_bindings():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "nextAction: nextWorkflowAction" in html
    assert "nextActionCta: nextWorkflowActionCta" in html
    assert "goToRequiredAction()" in js
    assert "nextRequiredAction = ko.pureComputed" in js
    assert "nextWorkflowAction = ko.pureComputed" in js
    assert "shouldShowNextRequiredAction = ko.pureComputed" in js
    assert "nextRequiredActionCta = ko.pureComputed" in js
    assert "nextWorkflowActionCta = ko.pureComputed" in js
    assert "Map primary outcome cohort" in js
    assert "Needed before validation, execution, analysis, and reporting." in js


def test_tte_manager_eligibility_overlay_defaults_to_review_copy():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "<!-- ko if: isProcessingEligibility() -->" in html
    assert 'text: capabilityProgressText' in html
    assert "visible: capabilityProgressDetailText(), text: capabilityProgressDetailText" in html
    assert "isProcessingEligibility = ko.observable(false);" in js
    assert "capabilityProgressDetailText = ko.observable('');" in js
    assert "Structuring criteria" in js
    assert "Turning the trial text into editable eligibility rules." in js
    assert "Preparing OMOP mapping" in js
    assert "Finding candidate OMOP concepts for the criteria." in js
    assert "Mapping criteria to OMOP (" in js
    assert "Applying concept mappings to the eligibility rules." in js
    assert "Target cohort mapped" in js
    assert "Continuing with criteria mapping." in js
    assert "this.isProcessingEligibility(true);" in js
    assert "this.capabilityProgressText('Structuring criteria');" in js
    assert "this.isProcessingEligibility(false);" in js


def test_tte_manager_wires_tte_gating_helpers_to_execution_dependent_actions():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "canTriggerValidation = ko.pureComputed" in js
    assert "canTriggerExecuteStudy = ko.pureComputed" in js
    assert "canTriggerRunAnalysis = ko.pureComputed" in js
    assert "canTriggerReportSummary = ko.pureComputed" in js
    assert 'data-bind="click: executeAnalysis, enable: canTriggerExecuteStudy' in html
    assert 'data-bind="click: triggerRunAnalysis, enable: canTriggerRunAnalysis' in html
    assert 'data-bind="click: triggerReportSummary, enable: canTriggerReportSummary' in html


def test_tte_frontend_wires_full_pipeline_endpoint_and_service():
    const_js = _atlas_dev_text("js", "pages", "target-trial-emulation", "const.js")
    service_js = _atlas_dev_text(
        "js", "pages", "target-trial-emulation", "services", "TTEService.js"
    )

    assert "run-full-pipeline" in const_js
    assert "runFullPipeline" in service_js


def test_tte_frontend_wires_seeded_cohort_generation_endpoint_and_service():
    repo_root = Path(__file__).resolve().parents[2]
    const_js = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "const.js"
    ).read_text()
    service_js = (
        repo_root
        / "atlas-dev"
        / "js"
        / "pages"
        / "target-trial-emulation"
        / "services"
        / "TTEService.js"
    ).read_text()

    assert "generate-seeded-cohorts" in const_js
    assert "generateSeededCohorts" in service_js


def test_tte_manager_renders_full_pipeline_controls_and_supervisor_metadata():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "pipelineButtonText()" in html
    assert "Full Pipeline Run" in html
    assert "Supervisor Hooks" in html
    assert "latestFullPipelineRun" in js
    assert "runFullPipeline" in js


def test_tte_manager_wires_inline_full_pipeline_feedback_and_enum_label_helper():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "tte-execution-feedback" in html
    assert "fullPipelineExecutionFeedback" in js
    assert "humanizeEnumLabel" in js


def test_tte_manager_renders_recommendation_first_analysis_tab_bindings():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "Analysis Recommendation" in html
    assert "Current diagnosis" in html
    assert "Why this method" in html
    assert "Why not the alternatives" in html
    assert "Proposed Parameters" in html
    assert "Apply Recommendation" in html
    assert "Manual override" in html
    assert "Refresh Recommendation" in html
    assert "analysisRecommendationTitle" in js
    assert "analysisDiagnosisFacts" in js
    assert "analysisRejectedAlternatives" in js
    assert "analysisProposedParameterEntries" in js
    assert "analysisAlternativeMethodOptions" in js
    assert "applyAnalysisStrategyRecommendation()" in js
    assert "requestAlternativeAnalysisStrategy(option)" in js
    assert "analysisManualOverrideOpen = ko.observable(false);" in js


def test_tte_browser_orders_recent_studies_by_visible_updated_column():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-browser.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-browser.js")

    assert "orderColumn: 2" in html
    assert "orderColumn: 4" not in html
    assert "title: ko.i18n('columns.updated', 'Updated')" in js


def test_tte_browser_uses_list_first_landing_with_new_analysis_action():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-browser.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-browser.js")

    assert "tte-browser-toolbar" in html
    assert "Recent TTE Studies" in html
    assert "New TTE Study" in html
    assert "NCT Trial Lookup" not in html
    assert "Preset Trial" not in html
    assert "e.g., NCT02465515" not in html
    assert "newAnalysis()" in js
    assert "constants.paths.createAnalysis()" in js


def test_tte_browser_zero_studies_browser_shell_stays_visible():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-browser.html")

    assert "Recent TTE Studies" in html
    assert "tte-recent-studies" in html
    assert "<faceted-datatable" in html
    assert 'faceted-datatable data-bind="visible: !loading() && reference().length > 0"' not in html
    assert "reference: reference" in html


def test_tte_browser_surfaces_clear_all_studies_failures_in_browser_ui():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-browser.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-browser.js")

    assert 'class="alert alert-danger"' in html
    assert "visible: clearStudiesError" in html
    assert "text: clearStudiesError" in html
    assert "this.clearStudiesError = ko.observable('');" in js
    assert "Failed to clear TTE studies" in js


def test_tte_browser_wires_clear_all_studies_danger_action():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-browser.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-browser.js")
    service_js = _atlas_dev_text(
        "js", "pages", "target-trial-emulation", "services", "TTEService.js"
    )

    assert "Clear All Studies" in html
    assert "click: clearAllStudies" in html
    assert "clearAllStudies()" in js
    assert "window.confirm(" in js
    assert "TTEService.clearStudies()" in js
    assert "clearStudies: function ()" in service_js


def test_tte_manager_renders_progressive_eligibility_loading_feedback():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "tte-eligibility-banner" in html
    assert "visible: shouldShowEligibilityMatrixBanner, css: [eligibilityMatrixBannerState()" in html
    assert "Loading seeded target population" in html
    assert "Loading seeded inclusion criteria" in html
    assert "Loading seeded exclusion criteria" in html
    assert 'click: addInclusionCriteria, disable: isImportingTrial()' in html
    assert 'click: addExclusionCriteria, disable: isImportingTrial()' in html
    assert "importPhaseDefinitions = {" in js
    assert "importPhaseSequence = [" in js
    assert "importPhaseTitle = ko.pureComputed" in js
    assert "importPhaseDescription = ko.pureComputed" in js
    assert "importPhaseItems = ko.pureComputed" in js
    assert "isTargetPopulationLoading" in js
    assert "isInclusionCriteriaLoading" in js
    assert "isExclusionCriteriaLoading" in js
    assert "eligibilityImportStatusTitle" in js
    assert "eligibilityImportStatusCopy" in js


def test_tte_manager_uses_matrix_artifact_freshness_signals_and_seeded_empty_placeholders():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "tte-eligibility-banner__meta" in html
    assert "tte-eligibility-banner__pill" in html
    assert "tte-seeded-section-placeholder" in html
    assert "No seeded inclusion criteria were imported from this trial." in html
    assert "No seeded exclusion criteria were imported from this trial." in html
    assert html.count("Add the criteria that still apply.") == 2
    assert "currentAppliedSeededImportArtifact = ko.pureComputed" in js
    assert "getLatestAppliedGenerateFromNctArtifact(this.artifacts())" in js
    assert "rehydratedSeededImportNctId = ko.pureComputed" in js
    assert "hasCompletedSeededImport" in js
    assert "structuredEligibilityShellSyncStatus = ko.observable('shell-only');" in js
    assert "this.structuredEligibilityShellSyncStatus('clean');" in js
    assert "this.structuredEligibilityShellSyncStatus('shell-stale');" in js
    assert "Rows changed after the last processed result." in js
    assert "showSeededEmptyInclusionCriteria" in js
    assert "showSeededEmptyExclusionCriteria" in js


def test_tte_manager_wires_structured_eligibility_editor_host():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")
    service_js = _atlas_dev_text(
        "js", "pages", "target-trial-emulation", "services", "TTEService.js"
    )
    const_js = _atlas_dev_text(
        "js", "pages", "target-trial-emulation", "const.js"
    )
    adapter_js = _atlas_dev_text(
        "js", "pages", "target-trial-emulation", "eligibility-expression-adapter.js"
    )
    host_js = _atlas_dev_text(
        "js",
        "pages",
        "target-trial-emulation",
        "components",
        "tte-eligibility-cohort-editor.js",
    )
    host_html = _atlas_dev_text(
        "js",
        "pages",
        "target-trial-emulation",
        "components",
        "tte-eligibility-cohort-editor.html",
    )

    assert "tte-eligibility-banner__primary" in html
    assert "with: $parent.eligibilityMatrixPrimaryAction" in html
    assert "click: click, text: label, enable: enabled" in html
    assert "tte-eligibility-banner__secondary" in html
    assert "tte-structured-editor-shell" in html
    assert "Eligibility Rows Stay Visible" in html
    assert "if: structuredEligibilityEditorOpen()" in html
    assert "visible: structuredEligibilityEditorOpen()" not in html
    assert "visible: structuredEligibilityEditorOpen" not in html
    assert "tte-eligibility-cohort-editor" in html
    assert "launchContext: structuredEligibilityLaunchContext" in html
    assert "onApply: applyStructuredEligibilityEdit" in html
    assert "onCancel: cancelStructuredEligibilityEdit" in html
    assert "launchEligibilityBuilder(context)" in js
    assert "structuredEligibilityPrimaryCtaLabel = ko.pureComputed" in js
    assert "? 'Open Builder'" in js
    assert ": 'Process Eligibility'" in js
    assert "processEligibility: function (studyId)" in service_js
    assert "constants.apiPaths.tteProcessEligibility(studyId)" in service_js
    assert "process" in service_js.lower() and "eligibility" in service_js.lower()
    assert "tteProcessEligibility: id => `${apiRoot}/tte/studies/${id}/process-eligibility`" in const_js
    assert "convertEligibilityToStructured(context)" in js
    assert "TTEService.processEligibility(studyId)" in js or "tteProcessEligibilityStream" in js
    assert "openStructuredEligibilityEditor(context, options)" in js
    assert "applyStructuredEligibilityEdit(expression)" in js
    assert "cancelStructuredEligibilityEdit()" in js
    assert "eligibilityStructuredExpression = ko.observable(null);" in js
    assert "processedEligibilityDraft = ko.observable(null);" in js
    assert "structuredEligibilityEditorOpen = ko.observable(false);" in js
    assert "structuredEligibilityFlowState = ko.observable('idle');" in js
    assert "structuredEligibilityShellSyncStatus = ko.observable('shell-only');" in js
    assert "structuredEligibilitySnapshotPrecedence = ko.pureComputed" in js
    assert "this.structuredEligibilityFlowState('processed');" in js
    assert "this.structuredEligibilityFlowState(" in js
    assert "? 'builder-open' : 'derived-preview'" in js
    assert "this.structuredEligibilityFlowState('applied');" in js
    assert "this.structuredEligibilityShellSyncStatus('clean');" in js
    assert "this.structuredEligibilityShellSyncStatus('shell-stale');" in js
    assert "populateFromStudy(study) {" in js
    assert "const structuredEligibilityExpression = eligibilityExpressionAdapter.normalizeStructuredExpression(" in js
    assert "this.eligibilityStructuredExpression(structuredEligibilityExpression);" in js
    assert "buildStudyData() {" in js
    assert "structuredExpression: this.eligibilityStructuredExpression()," in js
    assert "return this.ensureStudyForCapability()" in js
    assert "applyProcessedEligibilityArtifact(artifact)" in js
    assert "artifact.payload.proposedChanges.eligibility" in js
    assert "this.processedEligibilityDraft({" in js
    assert "const expression = (openOptions.forceExisting ? this.eligibilityStructuredExpression() : null)" in js
    assert "|| this.eligibilityStructuredExpression()" in js
    assert "const draftEligibility = openOptions.draftEligibility || null;" in js
    assert "draftEligibility ? draftEligibility.structuredExpression : expression" in js
    assert "this.structuredEligibilityEditorSource = draftEligibility ? 'draft' : 'canonical';" in js
    assert "const editorDraft = this.structuredEligibilityEditorSource === 'draft'" in js
    assert "this.processedEligibilityDraft(nextState);" in js
    assert "this.handleCapabilityResponse(response, {" in js
    assert "Draft artifact is ready for review." in js
    assert "buildStructuredExpressionFromEligibility" in adapter_js
    assert "buildEligibilitySummaryFromStructuredExpression" in adapter_js
    assert "normalizeStructuredExpression" in adapter_js
    assert "ko.components.register('tte-eligibility-cohort-editor'" in host_js
    assert "this.onApply(editedExpression);" in host_js
    assert "this.onCancel();" in host_js
    assert "ko.utils.domNodeDisposal.addDisposeCallback" in host_js
    assert "eligibilityExpressionAdapter.normalizeStructuredExpression(" in js
    assert "data-bind=\"click: apply\"" in host_html
    assert "data-bind=\"click: cancel\"" in host_html


def test_tte_manager_degraded_mode_guard_does_not_depend_on_page_constants_application_statuses():
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "isAppDegraded = ko.observable(false);" in js
    assert "updateDegradedState = () => {" in js
    assert "sharedState.appInitializationStatus()" in js
    assert "sharedState.sources().length > 0" in js
    assert "this.availableSources().length > 0" in js
    assert "|| !!this.selectedSourceKey()" in js
    assert "sharedState.appInitializationStatus.subscribe(this.updateDegradedState);" in js
    assert "sharedState.sources.subscribe(this.updateDegradedState);" in js
    assert "this.availableSources.subscribe(this.updateDegradedState);" in js
    assert "this.selectedSourceKey.subscribe(this.updateDegradedState);" in js
    assert "this.updateDegradedState();" in js
    assert "appStatus !== 'running'" in js
    assert "appStatus !== 'initializing'" in js
    assert "constants.applicationStatuses.running" not in js


def test_tte_manager_limits_execute_study_sources_to_research_benchmarks():
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "const EXECUTION_SOURCE_ALLOWLIST = [" in js
    assert "'LEADER_BENCHMARK'" in js
    assert "'PLATO_BENCHMARK'" in js
    assert "'ARISTOTLE_BENCHMARK'" in js
    assert "const EXECUTION_SOURCE_FALLBACKS = [" in js
    assert "Synthea LEADER Benchmark" in js
    assert "Synthea PLATO Benchmark" in js
    assert "Synthea ARISTOTLE Benchmark" in js
    assert "getVisibleExecutionSources(sources = []) {" in js
    assert "EXECUTION_SOURCE_ALLOWLIST.includes(source.sourceKey)" in js
    assert "const visibleSources = this.getVisibleExecutionSources(sources);" in js
    assert "this.syncSelectedExecutionSourceKey(visibleSources);" in js
    assert "this.syncSelectedExecutionSourceKey(fallbackSources);" in js
    assert "'SYNTHEA23M'" not in js


def test_tte_manager_exposes_process_result_ready_actions_for_eligibility():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "Definition Ready" in js
    assert "Reprocess Needed" in js
    assert "Open the generated result when you need cohort logic or concept sets." in js
    assert "Last processed result still available" in js
    assert "label: 'Open Builder'" in js
    assert "label: 'Reprocess Eligibility'" in js
    assert "label: 'Open Concept Sets'" in js
    assert "title: 'Concept Sets'" in js
    assert "detail: 'Review the generated concept sets for this eligibility definition.'" in js
    assert "focusMode: 'conceptsets'" in js
    assert "visible: $parent.eligibilityMatrixSecondaryActions && $parent.eligibilityMatrixSecondaryActions().length > 0" in html
    assert "click: click, text: label, enable: enabled, css: cssClass" in html


def test_tte_manager_treats_seeded_target_population_sentinel_as_seeded_empty():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "Target population to be specified" in js
    assert "isSeededEmptyTargetPopulationName" in js
    assert "normalizedTargetCohortName" in js
    assert "showSeededEmptyTargetPopulation" in js
    assert "value: normalizedTargetCohortName" in html
    assert "No seeded target population was imported from this trial." in html


def test_tte_manager_marks_processed_eligibility_stale_when_manual_target_changes():
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "applyTargetCohortSelection() {" in js
    assert "this.markEligibilityShellDirty();" in js


def test_tte_manager_normalizes_seeded_target_population_sentinel_in_persisted_payload():
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")

    assert "getPersistedTargetCohortName" in js
    assert "targetCohortName: this.getPersistedTargetCohortName()" in js


def test_tte_manager_criteria_rows_use_parent_import_guard_inside_foreach():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")

    assert 'value: description, disable: $parent.isImportingTrial()' in html
    assert 'click: $parent.removeInclusionCriteria.bind($parent), disable: $parent.isImportingTrial()' in html
    assert 'click: $parent.removeExclusionCriteria.bind($parent), disable: $parent.isImportingTrial()' in html


def test_tte_manager_add_criteria_uses_create_model_factory():
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")
    import re
    inc_match = re.search(r'addInclusionCriteria\(\)\s*\{[^}]+\}', js, re.DOTALL)
    exc_match = re.search(r'addExclusionCriteria\(\)\s*\{[^}]+\}', js, re.DOTALL)
    assert inc_match and "createEligibilityCriterionModel" in inc_match.group(0)
    assert exc_match and "createEligibilityCriterionModel" in exc_match.group(0)


def test_tte_manager_has_constraint_operator_display_map():
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")
    assert "OP_DISPLAY" in js
    assert "\\u2265" in js  # >=
    assert "\\u2264" in js  # <=


def test_tte_manager_criterion_model_has_editing_observable():
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")
    assert "isEditingConstraint" in js


def test_tte_manager_uses_constraint_badge_template():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    assert "tte-constraint-badge-template" in html
    assert html.count('id="tte-constraint-badge-template"') == 1
    import re
    usages = re.findall(r"template:\s*\{\s*name:\s*'tte-constraint-badge-template'", html)
    assert len(usages) >= 2


def test_tte_manager_criteria_model_has_stale_snapshot():
    js = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.js")
    assert "isStale" in js
    assert "_processedSnapshot" in js
    assert "snapshotEligibilityCriteria" in js


def test_tte_manager_has_stale_eligibility_warning_banner():
    html = _atlas_dev_text("js", "pages", "target-trial-emulation", "tte-manager.html")
    assert "eligibilityShellStale" in html
    assert "criteria-shell-row--stale" in html
    assert "Criteria changed since last processing" in html


def test_main_page_registry_does_not_register_legacy_nct_emulation_page():
    main_js = _atlas_dev_text("js", "pages", "main.js")

    assert "./nct-emulation/index" not in main_js
    assert "nctEmulation," not in main_js
