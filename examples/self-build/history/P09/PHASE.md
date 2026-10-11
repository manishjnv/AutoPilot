# Phase P09 — N7 guard on for new and adopted projects

- Closed: 2026-10-11
- Status: done
- Cost: $0.26

## Goal
The new-file guard (P07-T02) is opt-in and the template sets it to false, so no project gets it. New and adopted projects (`ap init`, plain `ap`) get `gate.new_file_reasons: true`; an existing project.yaml without the key keeps the old behaviour (off).


## Tasks
- [done] P09-T01 Template turns the new-file guard on; old project.yaml stays off
