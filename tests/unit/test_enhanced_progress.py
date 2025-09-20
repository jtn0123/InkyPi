"""Tests for enhanced progress tracking functionality."""

import pytest
from unittest.mock import Mock, patch
from src.utils.progress import (
    ProgressTracker,
    ProgressStep,
    track_progress,
    record_step,
    start_step,
    update_step,
    complete_step,
    fail_step,
    get_current_tracker
)


class TestProgressStep:
    """Test the ProgressStep dataclass."""

    def test_progress_step_creation(self):
        """Test creating a ProgressStep instance."""
        step = ProgressStep(
            name="test_step",
            description="Test step description",
            elapsed_ms=1500,
            status="completed"
        )

        assert step.name == "test_step"
        assert step.description == "Test step description"
        assert step.elapsed_ms == 1500
        assert step.status == "completed"
        assert step.error_message is None
        assert step.substeps == []

    def test_progress_step_with_error(self):
        """Test creating a ProgressStep with error information."""
        step = ProgressStep(
            name="failed_step",
            description="Failed step",
            elapsed_ms=2000,
            status="failed",
            error_message="Something went wrong"
        )

        assert step.status == "failed"
        assert step.error_message == "Something went wrong"

    def test_progress_step_with_substeps(self):
        """Test creating a ProgressStep with substeps."""
        substeps = ["Connect to API", "Parse response", "Validate data"]
        step = ProgressStep(
            name="api_call",
            description="Making API call",
            elapsed_ms=3000,
            status="completed",
            substeps=substeps
        )

        assert step.substeps == substeps


class TestProgressTracker:
    """Test the ProgressTracker class."""

    def test_tracker_initialization(self):
        """Test ProgressTracker initialization."""
        tracker = ProgressTracker()

        assert len(tracker.steps) == 0
        assert tracker._current_step is None
        assert not tracker.is_step_active()

    def test_simple_step_recording(self):
        """Test recording simple completed steps."""
        tracker = ProgressTracker()

        tracker.step("first_step", "First step description")
        tracker.step("second_step", "Second step description")

        steps = tracker.get_steps()
        assert len(steps) == 2

        assert steps[0].name == "first_step"
        assert steps[0].description == "First step description"
        assert steps[0].status == "completed"
        assert steps[0].elapsed_ms > 0

        assert steps[1].name == "second_step"
        assert steps[1].description == "Second step description"
        assert steps[1].status == "completed"

    def test_step_with_progress_tracking(self):
        """Test step tracking with start/update/complete flow."""
        tracker = ProgressTracker()

        # Start a step
        tracker.start_step("complex_step", "Starting complex operation")
        assert tracker.is_step_active()
        assert tracker.get_current_step_name() == "complex_step"

        steps = tracker.get_steps()
        assert len(steps) == 1
        assert steps[0].status == "in_progress"
        assert steps[0].elapsed_ms == 0

        # Update the step
        tracker.update_current_step("Processing data", ["Parse", "Validate", "Transform"])
        steps = tracker.get_steps()
        assert steps[0].description == "Processing data"
        assert steps[0].substeps == ["Parse", "Validate", "Transform"]

        # Complete the step
        tracker.complete_current_step("Operation completed successfully")
        assert not tracker.is_step_active()

        steps = tracker.get_steps()
        assert steps[0].status == "completed"
        assert steps[0].description == "Operation completed successfully"
        assert steps[0].elapsed_ms > 0

    def test_step_failure_tracking(self):
        """Test step failure tracking."""
        tracker = ProgressTracker()

        tracker.start_step("failing_step", "This will fail")
        tracker.fail_current_step("Network connection failed")

        assert not tracker.is_step_active()

        steps = tracker.get_steps()
        assert len(steps) == 1
        assert steps[0].status == "failed"
        assert steps[0].error_message == "Network connection failed"
        assert steps[0].elapsed_ms > 0

    def test_total_elapsed_time(self):
        """Test total elapsed time calculation."""
        tracker = ProgressTracker()

        # Add a small delay to ensure elapsed time > 0
        import time
        time.sleep(0.01)

        total_time = tracker.get_total_elapsed_ms()
        assert total_time > 0

    def test_multiple_steps_timing(self):
        """Test that multiple steps have proper timing."""
        tracker = ProgressTracker()

        tracker.step("step1", "First step")

        # Add delay to ensure different timing
        import time
        time.sleep(0.01)

        tracker.step("step2", "Second step")

        steps = tracker.get_steps()
        assert len(steps) == 2

        # Both steps should have positive elapsed time
        assert steps[0].elapsed_ms > 0
        assert steps[1].elapsed_ms > 0


class TestProgressContextManager:
    """Test the progress tracking context manager."""

    def test_track_progress_context(self):
        """Test the track_progress context manager."""
        # Initially no tracker
        assert get_current_tracker() is None

        with track_progress() as tracker:
            # Tracker should be available in context
            assert tracker is not None
            assert get_current_tracker() is tracker

            # Can record steps
            tracker.step("test_step", "Test step in context")

            steps = tracker.get_steps()
            assert len(steps) == 1
            assert steps[0].name == "test_step"

        # Tracker should be None after context
        assert get_current_tracker() is None

    def test_nested_progress_tracking(self):
        """Test that nested tracking works correctly."""
        with track_progress() as outer_tracker:
            outer_tracker.step("outer_step", "Outer step")

            with track_progress() as inner_tracker:
                # Inner tracker should be the active one
                assert get_current_tracker() is inner_tracker
                inner_tracker.step("inner_step", "Inner step")

            # Outer tracker should be active again
            assert get_current_tracker() is outer_tracker


class TestProgressHelperFunctions:
    """Test the progress tracking helper functions."""

    def test_record_step_without_tracker(self):
        """Test record_step when no tracker is active."""
        # Should not raise an error
        record_step("test_step", "Test description")

    def test_record_step_with_tracker(self):
        """Test record_step with active tracker."""
        with track_progress() as tracker:
            record_step("helper_step", "Step via helper function")

            steps = tracker.get_steps()
            assert len(steps) == 1
            assert steps[0].name == "helper_step"
            assert steps[0].description == "Step via helper function"

    def test_start_step_helper(self):
        """Test start_step helper function."""
        with track_progress() as tracker:
            start_step("async_step", "Starting async operation")

            assert tracker.is_step_active()
            assert tracker.get_current_step_name() == "async_step"

    def test_update_step_helper(self):
        """Test update_step helper function."""
        with track_progress() as tracker:
            start_step("update_test", "Initial description")
            update_step("Updated description", ["substep1", "substep2"])

            steps = tracker.get_steps()
            assert steps[0].description == "Updated description"
            assert steps[0].substeps == ["substep1", "substep2"]

    def test_complete_step_helper(self):
        """Test complete_step helper function."""
        with track_progress() as tracker:
            start_step("complete_test", "Will be completed")
            complete_step("Completed successfully")

            assert not tracker.is_step_active()

            steps = tracker.get_steps()
            assert steps[0].status == "completed"
            assert steps[0].description == "Completed successfully"

    def test_fail_step_helper(self):
        """Test fail_step helper function."""
        with track_progress() as tracker:
            start_step("fail_test", "Will fail")
            fail_step("Failed with error")

            assert not tracker.is_step_active()

            steps = tracker.get_steps()
            assert steps[0].status == "failed"
            assert steps[0].error_message == "Failed with error"

    def test_helper_functions_without_tracker(self):
        """Test that helper functions don't error without active tracker."""
        # None of these should raise errors
        start_step("test", "test")
        update_step("test")
        complete_step("test")
        fail_step("test")


class TestProgressTrackerEdgeCases:
    """Test edge cases and error conditions."""

    def test_complete_step_without_active_step(self):
        """Test completing a step when none is active."""
        tracker = ProgressTracker()

        # Should not raise an error
        tracker.complete_current_step("No active step")

        # Should have no steps
        assert len(tracker.get_steps()) == 0

    def test_update_step_without_active_step(self):
        """Test updating a step when none is active."""
        tracker = ProgressTracker()

        # Should not raise an error
        tracker.update_current_step("No active step")

        # Should have no steps
        assert len(tracker.get_steps()) == 0

    def test_fail_step_without_active_step(self):
        """Test failing a step when none is active."""
        tracker = ProgressTracker()

        # Should not raise an error
        tracker.fail_current_step("No active step")

        # Should have no steps
        assert len(tracker.get_steps()) == 0

    def test_multiple_start_steps_without_completion(self):
        """Test starting multiple steps without completing previous ones."""
        tracker = ProgressTracker()

        tracker.start_step("step1", "First step")
        tracker.start_step("step2", "Second step")

        # Should have two steps, both in progress
        steps = tracker.get_steps()
        assert len(steps) == 2
        assert all(step.status == "in_progress" for step in steps)

        # Current step should be the latest one
        assert tracker.get_current_step_name() == "step2"


class TestProgressTrackerIntegration:
    """Test integration scenarios."""

    def test_mixed_step_types(self):
        """Test mixing simple steps with complex start/complete steps."""
        tracker = ProgressTracker()

        # Simple step
        tracker.step("simple1", "Simple step 1")

        # Complex step
        tracker.start_step("complex1", "Complex step")
        tracker.update_current_step("Updated complex step")
        tracker.complete_current_step("Complex step completed")

        # Another simple step
        tracker.step("simple2", "Simple step 2")

        steps = tracker.get_steps()
        assert len(steps) == 3

        assert steps[0].name == "simple1"
        assert steps[0].status == "completed"

        assert steps[1].name == "complex1"
        assert steps[1].status == "completed"
        assert steps[1].description == "Complex step completed"

        assert steps[2].name == "simple2"
        assert steps[2].status == "completed"

    def test_step_description_defaults(self):
        """Test that step descriptions default appropriately."""
        tracker = ProgressTracker()

        # Step with no description should use name as description
        tracker.step("test_step")

        steps = tracker.get_steps()
        assert steps[0].description == "test_step"

        # Start step with no description
        tracker.start_step("another_step")
        tracker.complete_current_step()

        steps = tracker.get_steps()
        assert steps[1].description == "another_step"