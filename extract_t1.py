#!/usr/bin/env python3
"""
dump the full rendered prompt for each starting agent.
"""

import os

from python.bootstrap import build_starting_world
from python.locations import describe_home_location
from python.prompting import build_messages, render_prompt


def extract_all_prompts() -> None:
    world = build_starting_world()
    output_path = os.path.join(os.path.dirname(__file__), "prompt.log")

    with open(output_path, "w", encoding="utf-8") as f:
        for agent_id in sorted(world.agents.keys()):
            agent = world.agents[agent_id]
            notifications = ""
            msgs = build_messages(agent_id, world, notifications)
            prompt_text = render_prompt(msgs)

            f.write(f"AGENT {agent.id}: {agent.name}\n")
            f.write(
                f"Home: Home_{agent.name} ({describe_home_location(agent.home_location)}) | "
                f"Job: {agent.job} | Cash: ${agent.money:.2f}\n"
            )
            f.write("=" * 100 + "\n")
            f.write(prompt_text)
            f.write("\n" + "=" * 100 + "\n\n")

            print(f"Wrote prompt for {agent.name}.")

    print(f"\nAll prompts written to: {output_path}")


if __name__ == "__main__":
    extract_all_prompts()