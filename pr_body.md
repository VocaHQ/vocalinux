## Description

Why #900 happens: `find_keyboard_devices()` treats any input device with a nonzero `EV_KEY` bitmap as a keyboard, which includes Logitech mice (G502, MX Master 3) whose programmable-button interfaces report key bits. The evdev backend then grabs the mouse node (`EVIOCGRAB`) and re-emits every event, `EV_REL` pointer motion included, through a paired uinput clone. All cursor movement goes through the Python reader thread, which shows up as a periodic cursor hitch (about every 10 seconds in the report) and `SYN_DROPPED` warnings whenever a motion burst overflows the kernel buffer.

Changes:

- `_parse_keyboard_devices_from_proc` now collects the whole device block (name, handlers, `KEY`/`REL`/`ABS` bitmaps) before deciding, and skips blocks that report pointer motion: `REL_X`+`REL_Y` or `ABS_X`+`ABS_Y` set in the low word of the bitmap.
- `_find_keyboard_devices_from_evdev` applies the same exclusion via `capabilities()`, covering the snap-confinement fallback path.
- Wheel-only devices (`REL_WHEEL`) and real keyboards are unaffected, and a mouse's separate "Keyboard" interface node stays monitored, so shortcuts mapped onto mouse buttons keep working.

Skipping the pointer node also removes a quieter problem: a motion flood could overflow the reader's kernel buffer, and the `SYN_DROPPED` recovery then reset per-engine combo state shared by all keyboards.

## Related issue

Fixes #900

## Type of change

- [x] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation
- [ ] Refactor
- [ ] Tests
- [ ] Packaging / CI

## Checklist

- [x] Code follows project style (Black, isort, flake8)
- [ ] Documentation updated when user-facing behavior or install steps change (N/A - no documented behavior changes)
- [x] Tests added or updated for the change
- [x] Local tests pass (`pytest`)
- [x] Conventional commit message style

## Notes for reviewers

- Verified with real uinput devices on Linux: a mouse (`EV_KEY` + `REL_X/Y`), a tablet (`ABS_X/Y`), a keyboard, and a wheel-only keyboard. Both discovery paths skip the two pointers and keep the two keyboards.
- Full `pytest` suite passes locally.
