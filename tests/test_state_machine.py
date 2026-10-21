"""Scene stack: lifecycle, opaque overlay drawing, transitions, context."""

from __future__ import annotations

import unittest

import pygame

from pongpro.core.state_machine import Scene, SceneStack, Transition

pygame.init()
pygame.font.init()


class RecordingScene(Scene):
    def __init__(self, name: str, opaque: bool = True) -> None:
        super().__init__()
        self.name = name
        self.opaque = opaque
        self.log: list[str] = []

    def update(self, dt: float) -> None:
        self.log.append("update")

    def draw(self, surface: pygame.Surface) -> None:
        self.log.append("draw")

    def on_enter(self, **kwargs) -> None:
        self.log.append(f"enter:{kwargs.get('tag', '')}")

    def on_exit(self) -> None:
        self.log.append("exit")

    def on_resume(self) -> None:
        self.log.append("resume")

    def on_cover(self) -> None:
        self.log.append("cover")

    def handle_event(self, event: pygame.event.Event) -> None:
        self.log.append("event")


class SceneStackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = SceneStack((320, 180), ctx={"probe": True})
        self.surface = pygame.Surface((320, 180))

    def test_push_calls_lifecycle(self) -> None:
        scene = RecordingScene("a")
        self.stack.push(scene, transition=Transition.NONE, tag="hello")
        self.assertIs(self.stack.current, scene)
        self.assertIn("enter:hello", scene.log)
        self.assertIs(scene.stack, self.stack)
        self.assertEqual(scene.ctx, {"probe": True})

    def test_only_top_scene_updates(self) -> None:
        bottom = RecordingScene("bottom")
        top = RecordingScene("top")
        self.stack.push(bottom, transition=Transition.NONE)
        self.stack.push(top, transition=Transition.NONE)
        self.stack.update(1 / 120)
        self.assertEqual(bottom.log.count("update"), 0)
        self.assertEqual(top.log.count("update"), 1)

    def test_opaque_overlay_draws_scene_below(self) -> None:
        bottom = RecordingScene("bottom", opaque=True)
        overlay = RecordingScene("overlay", opaque=False)
        self.stack.push(bottom, transition=Transition.NONE)
        self.stack.push(overlay, transition=Transition.NONE)
        self.stack.draw(self.surface)
        self.assertEqual(bottom.log.count("draw"), 1)
        self.assertEqual(overlay.log.count("draw"), 1)

    def test_opaque_top_hides_scene_below(self) -> None:
        bottom = RecordingScene("bottom", opaque=True)
        top = RecordingScene("top", opaque=True)
        self.stack.push(bottom, transition=Transition.NONE)
        self.stack.push(top, transition=Transition.NONE)
        self.stack.draw(self.surface)
        self.assertEqual(bottom.log.count("draw"), 0)
        self.assertEqual(top.log.count("draw"), 1)

    def test_cover_and_resume_hooks(self) -> None:
        bottom = RecordingScene("bottom")
        top = RecordingScene("top")
        self.stack.push(bottom, transition=Transition.NONE)
        self.stack.push(top, transition=Transition.NONE)
        self.assertIn("cover", bottom.log)
        self.stack.pop(transition=Transition.NONE)
        self.assertIn("resume", bottom.log)
        self.assertIn("exit", top.log)

    def test_events_only_reach_top_scene(self) -> None:
        bottom = RecordingScene("bottom")
        top = RecordingScene("top")
        self.stack.push(bottom, transition=Transition.NONE)
        self.stack.push(top, transition=Transition.NONE)
        self.stack.handle_event(pygame.event.Event(pygame.KEYDOWN, key=1))
        self.assertEqual(bottom.log.count("event"), 0)
        self.assertEqual(top.log.count("event"), 1)

    def test_replace_swaps_top(self) -> None:
        first = RecordingScene("first")
        second = RecordingScene("second")
        self.stack.push(first, transition=Transition.NONE)
        self.stack.replace(second, transition=Transition.NONE)
        self.assertIs(self.stack.current, second)
        self.assertIn("exit", first.log)
        self.assertEqual(self.stack.depth, 1)

    def test_faded_transition_is_deferred_until_animation_finishes(self) -> None:
        first = RecordingScene("first")
        second = RecordingScene("second")
        self.stack.push(first, transition=Transition.NONE)
        self.stack.push(second, transition=Transition.FADE)
        # The swap has not happened yet: still mid fade-out.
        self.assertIs(self.stack.current, first)
        self.assertTrue(self.stack.transitioning)
        for _ in range(120):  # 1s of fixed steps is plenty for a fade
            self.stack.update(1 / 120)
        self.assertIs(self.stack.current, second)
        self.assertNotIn("update", second.log[:1])  # created during the swap

    def test_pop_to_removes_scenes_above_target(self) -> None:
        bottom = RecordingScene("bottom")
        middle = RecordingScene("middle")
        top = RecordingScene("top")
        for scene in (bottom, middle, top):
            self.stack.push(scene, transition=Transition.NONE)
        self.stack.pop_to(RecordingScene, transition=Transition.NONE)
        self.assertIs(self.stack.current, top)
        self.assertEqual(self.stack.depth, 3)

        # Now pop_to the specific instance type while it is not on top.
        self.stack.pop_to(RecordingScene, transition=Transition.NONE)
        self.assertEqual(self.stack.depth, 3)

    def test_replace_top_builds_a_new_stack_top(self) -> None:
        bottom = RecordingScene("bottom")
        middle = RecordingScene("middle")
        top = RecordingScene("top")
        for scene in (bottom, middle, top):
            self.stack.push(scene, transition=Transition.NONE)
        fresh = RecordingScene("fresh")
        self.stack.replace_top(2, fresh, transition=Transition.NONE)
        self.assertIs(self.stack.current, fresh)
        self.assertEqual(self.stack.depth, 2)
        self.assertIn("exit", middle.log)
        self.assertIn("exit", top.log)
        self.assertNotIn("exit", bottom.log)

    def test_find_returns_topmost_matching_scene(self) -> None:
        first = RecordingScene("first")
        second = RecordingScene("second")
        self.stack.push(first, transition=Transition.NONE)
        self.stack.push(second, transition=Transition.NONE)
        self.assertIs(self.stack.find(RecordingScene), second)

    def test_empty_stack_draws_black(self) -> None:
        self.stack.draw(self.surface)
        self.assertEqual(self.surface.get_at((0, 0))[:3], (0, 0, 0))

    def test_clear_empties_everything(self) -> None:
        for i in range(3):
            self.stack.push(RecordingScene(f"s{i}"), transition=Transition.NONE)
        self.stack.clear()
        self.assertEqual(self.stack.depth, 0)
        self.assertIsNone(self.stack.current)


if __name__ == "__main__":
    unittest.main()
