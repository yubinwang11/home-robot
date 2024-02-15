# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import random
import time
from typing import Callable, List

import numpy as np

from home_robot.motion.base import Planner, PlanResult
from home_robot.motion.rrt import TreeNode


class SimplifyXYT(Planner):
    """Define RRT planning problem and parameters. Holds two different trees and tries to connect them with some probabability."""

    # For floating point comparisons
    theta_tol = 1e-8

    def __init__(
        self,
        planner: Planner,
        min_step: float = 0.1,
        max_step: float = 1.0,
        num_steps: int = 6,
        min_angle: float = np.deg2rad(5),
    ):
        self.min_step = min_step
        self.max_step = max_step
        self.num_steps = num_steps
        self.min_angle = min_angle
        self.planner = planner
        self.reset()

    def reset(self):
        self.nodes = None

    def plan(self, start, goal, verbose: bool = False, **kwargs) -> PlanResult:
        """Do plan simplification"""
        self.planner.reset()
        verbose = True
        if verbose:
            print("Call internal planner")
        res = self.planner.plan(start, goal, verbose=verbose, **kwargs)
        self.nodes = self.planner.nodes
        if not res.success or len(res.trajectory) < 4:
            # Planning failed so nothing to do here
            return res

        for step in np.linspace(self.max_step, self.min_step, self.num_steps):

            # The last node we explored
            prev_node = None
            # The last node in simplified sequence
            anchor_node = None
            # Cumulative distance so far (cartesian only)
            cum_dist = 0
            # angle between last 2 waypoints to make sure we're going in the same direction
            prev_theta = None
            # New trajectory
            new_nodes = []

            for i, node in enumerate(res.trajectory):
                if verbose:
                    print()
                    print()
                    print(i + 1, "/", len(self.nodes))
                    print(
                        "anchor =",
                        anchor_node.state if anchor_node is not None else None,
                    )
                # Set the last node in the simplified sequence
                if anchor_node is None:
                    cum_dist = 0
                    new_nodes.append(TreeNode(parent=anchor_node, state=node.state))
                    prev_node = node
                    anchor_node = node
                    prev_theta = None
                else:
                    # Check to see if we can simplify by skipping this node, or if we should add it
                    assert prev_node is not None
                    x, y = prev_node.state[:2] - node.state[:2]
                    cur_theta = np.arctan2(y, x)
                    if prev_theta is None:
                        # theta_dist = node.state[-1] - prev_node.state[-1]
                        theta_dist = 0
                    else:
                        if verbose:
                            print(f"{prev_theta=}, {cur_theta=}")
                        theta_dist = prev_theta - cur_theta
                    dist = np.linalg.norm(node.state[:2] - prev_node.state[:2])
                    cum_dist += dist
                    if verbose:
                        print(node.state[-1], prev_node.state[-1])
                        print("theta dist =", theta_dist)
                        print("dist", dist)
                        print("cumulative", cum_dist)
                    if i == len(self.nodes) - 1:
                        new_nodes.append(TreeNode(parent=anchor_node, state=node.state))
                        # We're done
                        if verbose:
                            print("===========")
                        break
                    elif theta_dist < self.theta_tol:
                        if cum_dist >= step:
                            # Add it to the stack
                            if verbose:
                                print("add to stack")
                            new_nodes.append(
                                TreeNode(parent=anchor_node, state=prev_node.state)
                            )
                            anchor_node = prev_node
                            cum_dist = 0

                    else:
                        # We turned, so start again from here
                        if verbose:
                            print()
                            print("!!!!!!!!")
                            print("we turned")
                        new_nodes.append(
                            TreeNode(parent=anchor_node, state=prev_node.state)
                        )
                        anchor_node = prev_node
                        cum_dist = 0

                    if verbose:
                        print("simplified =", [x.state for x in new_nodes])
                    # breakpoint()
                    prev_node = node
                    prev_theta = cur_theta
            break

        if new_nodes is not None:
            return PlanResult(True, new_nodes)
        else:
            return PlanResult(False, reason="simplification and verification failed!")


if __name__ == "__main__":
    from home_robot.motion.rrt_connect import RRTConnect
    from home_robot.motion.shortcut import Shortcut
    from home_robot.utils.simple_env import SimpleEnv

    start, goal, obs = np.array([1.0, 1.0]), np.array([9.0, 9.0]), np.array([0.0, 9.0])
    env = SimpleEnv(obs)
    planner0 = RRTConnect(env.get_space(), env.validate)
    planner1 = Shortcut(planner0)
    planner2 = SimplifyXYT(planner1, max_step=5.0)

    def eval(planner):
        random.seed(0)
        np.random.seed(0)
        res = planner.plan(start, goal)
        print("Success:", res.success)
        if res.success:
            print("Plan =")
            for i, n in enumerate(res.trajectory):
                print(f"\t{i} = {n.state}")

        return res.get_length(), [node.state for node in res.trajectory]

    len0, plan0 = eval(planner0)
    len1, plan1 = eval(planner1)
    len2, plan2 = eval(planner2)
    print(f"{len0=} {len1=} {len2=}")

    env.show(plan1)
    env.show(plan2)
