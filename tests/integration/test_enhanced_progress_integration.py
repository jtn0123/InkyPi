"""Integration tests for enhanced progress tracking in plugin operations."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.utils.progress import track_progress, get_current_tracker
from src.plugins.base_plugin.base_plugin import BasePlugin


class TestProgressTrackingIntegration:
    """Test integration of progress tracking with plugin operations."""

    def test_base_plugin_uses_progress_tracking(self):
        """Test that BasePlugin uses enhanced progress tracking."""
        # Create a mock plugin config
        mock_config = {
            'id': 'test_plugin',
            'display_name': 'Test Plugin'
        }

        # Create plugin instance
        plugin = BasePlugin(mock_config)

        # Mock the template environment and screenshot function
        with patch.object(plugin.env, 'get_template') as mock_get_template, \
             patch('src.plugins.base_plugin.base_plugin.take_screenshot_html') as mock_screenshot, \
             patch('builtins.open', create=True) as mock_open:

            # Setup mocks
            mock_template = Mock()
            mock_template.render.return_value = "<html>test</html>"
            mock_get_template.return_value = mock_template

            mock_screenshot.return_value = Mock()  # Mock PIL Image

            # Mock file operations for CSS reading
            mock_open.return_value.__enter__.return_value.read.return_value = "/* test css */"

            # Track progress during render_image call
            with track_progress() as tracker:
                try:
                    plugin.render_image(
                        dimensions=(400, 300),
                        html_file="test.html",
                        css_file="test.css"
                    )
                except Exception:
                    # We expect some exceptions due to mocking, but we're testing progress tracking
                    pass

                # Verify that progress steps were recorded
                steps = tracker.get_steps()
                assert len(steps) >= 2  # At least template and screenshot steps

                # Check for template step
                template_steps = [s for s in steps if s.name == "template"]
                assert len(template_steps) >= 1

                # Check for screenshot step
                screenshot_steps = [s for s in steps if s.name == "screenshot"]
                assert len(screenshot_steps) >= 1

    def test_progress_tracking_with_template_error(self):
        """Test progress tracking when template rendering fails."""
        mock_config = {'id': 'test_plugin'}
        plugin = BasePlugin(mock_config)

        with patch.object(plugin.env, 'get_template') as mock_get_template, \
             patch('builtins.open', create=True):

            # Make template rendering fail
            mock_get_template.side_effect = Exception("Template not found")

            with track_progress() as tracker:
                with pytest.raises(Exception):
                    plugin.render_image(
                        dimensions=(400, 300),
                        html_file="missing.html"
                    )

                # Should have recorded a failed template step
                steps = tracker.get_steps()
                template_steps = [s for s in steps if s.name == "template"]
                assert len(template_steps) >= 1

                # The template step should be marked as failed
                assert any(s.status == "failed" for s in template_steps)
                assert any("Template rendering failed" in s.error_message for s in template_steps if s.error_message)

    def test_progress_tracking_with_screenshot_error(self):
        """Test progress tracking when screenshot capture fails."""
        mock_config = {'id': 'test_plugin'}
        plugin = BasePlugin(mock_config)

        with patch.object(plugin.env, 'get_template') as mock_get_template, \
             patch('src.plugins.base_plugin.base_plugin.take_screenshot_html') as mock_screenshot, \
             patch('builtins.open', create=True) as mock_open:

            # Setup successful template rendering
            mock_template = Mock()
            mock_template.render.return_value = "<html>test</html>"
            mock_get_template.return_value = mock_template
            mock_open.return_value.__enter__.return_value.read.return_value = "/* css */"

            # Make screenshot fail
            mock_screenshot.side_effect = Exception("Screenshot failed")

            with track_progress() as tracker:
                with pytest.raises(Exception):
                    plugin.render_image(
                        dimensions=(400, 300),
                        html_file="test.html"
                    )

                # Should have both template (success) and screenshot (failed) steps
                steps = tracker.get_steps()

                template_steps = [s for s in steps if s.name == "template"]
                screenshot_steps = [s for s in steps if s.name == "screenshot"]

                assert len(template_steps) >= 1
                assert len(screenshot_steps) >= 1

                # Template should succeed, screenshot should fail
                assert any(s.status == "completed" for s in template_steps)
                assert any(s.status == "failed" for s in screenshot_steps)

    def test_progress_tracking_step_timing(self):
        """Test that progress tracking records proper timing information."""
        mock_config = {'id': 'test_plugin'}
        plugin = BasePlugin(mock_config)

        with patch.object(plugin.env, 'get_template') as mock_get_template, \
             patch('src.plugins.base_plugin.base_plugin.take_screenshot_html') as mock_screenshot, \
             patch('builtins.open', create=True) as mock_open:

            # Setup mocks with small delays to ensure timing
            mock_template = Mock()
            mock_template.render.return_value = "<html>test</html>"
            mock_get_template.return_value = mock_template

            def delayed_screenshot(*args, **kwargs):
                import time
                time.sleep(0.01)  # Small delay to ensure measurable time
                return Mock()

            mock_screenshot.side_effect = delayed_screenshot
            mock_open.return_value.__enter__.return_value.read.return_value = "/* css */"

            with track_progress() as tracker:
                try:
                    plugin.render_image(
                        dimensions=(400, 300),
                        html_file="test.html"
                    )
                except Exception:
                    pass

                steps = tracker.get_steps()

                # All steps should have positive elapsed time
                for step in steps:
                    assert step.elapsed_ms > 0

                # Total elapsed time should be sum of step times
                total_step_time = sum(s.elapsed_ms for s in steps)
                total_tracker_time = tracker.get_total_elapsed_ms()

                # Total tracker time should be at least as much as step times
                assert total_tracker_time >= total_step_time

    def test_progress_tracking_step_descriptions(self):
        """Test that progress steps have meaningful descriptions."""
        mock_config = {'id': 'test_plugin'}
        plugin = BasePlugin(mock_config)

        with patch.object(plugin.env, 'get_template') as mock_get_template, \
             patch('src.plugins.base_plugin.base_plugin.take_screenshot_html') as mock_screenshot, \
             patch('builtins.open', create=True) as mock_open:

            mock_template = Mock()
            mock_template.render.return_value = "<html>test</html>"
            mock_get_template.return_value = mock_template
            mock_screenshot.return_value = Mock()
            mock_open.return_value.__enter__.return_value.read.return_value = "/* css */"

            with track_progress() as tracker:
                try:
                    plugin.render_image(
                        dimensions=(400, 300),
                        html_file="test_template.html"
                    )
                except Exception:
                    pass

                steps = tracker.get_steps()

                # Template step should have meaningful description
                template_steps = [s for s in steps if s.name == "template"]
                if template_steps:
                    assert "test_template.html" in template_steps[0].description

                # Screenshot step should have meaningful description
                screenshot_steps = [s for s in steps if s.name == "screenshot"]
                if screenshot_steps:
                    assert any(
                        word in screenshot_steps[0].description.lower()
                        for word in ["screenshot", "capture", "html"]
                    )

    def test_nested_progress_tracking(self):
        """Test that progress tracking works with nested operations."""
        mock_config = {'id': 'test_plugin'}
        plugin = BasePlugin(mock_config)

        with patch.object(plugin.env, 'get_template') as mock_get_template, \
             patch('src.plugins.base_plugin.base_plugin.take_screenshot_html') as mock_screenshot, \
             patch('builtins.open', create=True) as mock_open:

            mock_template = Mock()
            mock_template.render.return_value = "<html>test</html>"
            mock_get_template.return_value = mock_template
            mock_screenshot.return_value = Mock()
            mock_open.return_value.__enter__.return_value.read.return_value = "/* css */"

            # Outer progress tracker
            with track_progress() as outer_tracker:
                outer_tracker.step("outer_setup", "Setting up outer operation")

                # Inner progress tracker (simulating plugin operation)
                with track_progress() as inner_tracker:
                    try:
                        plugin.render_image(
                            dimensions=(400, 300),
                            html_file="test.html"
                        )
                    except Exception:
                        pass

                    # Inner tracker should have plugin steps
                    inner_steps = inner_tracker.get_steps()
                    assert len(inner_steps) >= 2

                outer_tracker.step("outer_completion", "Completing outer operation")

                # Outer tracker should have outer steps only
                outer_steps = outer_tracker.get_steps()
                assert len(outer_steps) == 2
                assert outer_steps[0].name == "outer_setup"
                assert outer_steps[1].name == "outer_completion"


class TestProgressTrackingHelpers:
    """Test the global progress tracking helper functions."""

    def test_progress_helpers_in_context(self):
        """Test that global helper functions work within tracking context."""
        from src.utils.progress import record_step, start_step, complete_step

        with track_progress() as tracker:
            # Use global helpers
            record_step("global_step1", "First global step")
            start_step("global_step2", "Starting second step")
            complete_step("Second step completed")

            steps = tracker.get_steps()
            assert len(steps) == 2

            assert steps[0].name == "global_step1"
            assert steps[0].status == "completed"

            assert steps[1].name == "global_step2"
            assert steps[1].status == "completed"
            assert steps[1].description == "Second step completed"

    def test_progress_helpers_without_context(self):
        """Test that global helpers don't break without tracking context."""
        from src.utils.progress import record_step, start_step, complete_step, fail_step

        # These should not raise errors even without tracking context
        record_step("orphan_step", "Orphaned step")
        start_step("orphan_start", "Orphaned start")
        complete_step("Orphaned completion")
        fail_step("Orphaned failure")

        # No tracker should be active
        assert get_current_tracker() is None


class TestProgressTrackingErrorHandling:
    """Test error handling in progress tracking."""

    def test_progress_tracking_survives_plugin_errors(self):
        """Test that progress tracking continues to work even if plugin operations fail."""
        mock_config = {'id': 'failing_plugin'}
        plugin = BasePlugin(mock_config)

        with patch.object(plugin.env, 'get_template') as mock_get_template:
            # Make everything fail
            mock_get_template.side_effect = RuntimeError("Everything is broken")

            with track_progress() as tracker:
                # Plugin operation should fail but not break progress tracking
                with pytest.raises(RuntimeError):
                    plugin.render_image(
                        dimensions=(400, 300),
                        html_file="broken.html"
                    )

                # Progress tracking should still work
                tracker.step("post_failure", "After the failure")

                steps = tracker.get_steps()
                assert len(steps) >= 1

                # Should have at least the manual step we added
                post_failure_steps = [s for s in steps if s.name == "post_failure"]
                assert len(post_failure_steps) == 1

    def test_progress_tracking_concurrent_access(self):
        """Test that progress tracking handles concurrent access gracefully."""
        import threading
        import time

        results = []

        def worker(worker_id):
            with track_progress() as tracker:
                tracker.step(f"worker_{worker_id}_start", f"Worker {worker_id} starting")
                time.sleep(0.01)  # Small delay
                tracker.step(f"worker_{worker_id}_end", f"Worker {worker_id} ending")

                steps = tracker.get_steps()
                results.append((worker_id, len(steps)))

        # Start multiple threads
        threads = []
        for i in range(3):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all threads to complete
        for t in threads:
            t.join()

        # Each worker should have recorded exactly 2 steps
        assert len(results) == 3
        for worker_id, step_count in results:
            assert step_count == 2, f"Worker {worker_id} should have 2 steps, got {step_count}"