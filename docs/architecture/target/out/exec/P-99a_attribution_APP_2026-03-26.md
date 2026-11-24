# P-95 attribution APP 2026-03-26

Descriptive, 1 day. APP 2026-03-26.
Engine config: configs/bt_position_arbitrary_not_calibrated.yaml
Legacy config: configs/bt_position_legacy_arm.yaml
signal-order trace linkage (D-252)
not evidence of edge, evaluation.md §1
classes
SAME 0 0 0
EXIT_CHANGED 1 295.76 -78.79
ENTRY_CHANGED 14 -151.54 -395.74
LEGACY_ONLY 17 -153.87 0
ENGINE_ONLY 19 0 -846.62
UNEXPLAINED 0 0 0
explanations
EXIT_CHANGED '' 1
ENTRY_CHANGED '' 14
LEGACY_ONLY 'NO_ORDER:resting_order_guard_blocked_duplicate_passive_order' 1
LEGACY_ONLY 'RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' 16
ENGINE_ONLY 'LEGACY_IN_POSITION' 12
ENGINE_ONLY 'NO_ORDER:resting_order_guard_blocked_duplicate_passive_order' 7
SAME (none)
UNEXPLAINED (none)
legacy_reasons
SIGNAL_REVERSE 32
exit_mix
{"ADVERSE": 32, "HORIZON": 2}
refusals legacy {}
refusals engine {"NO_SCALE_IN": 3}
suppressions legacy 0 {}
suppressions engine 7 {"SYMBOL_QUIET": 7}
unexplained 0
episodes
1 EXIT_CHANGED APP sig_position_fixture_v1 1774532160016354506 1 legacy_side=SHORT engine_side=SHORT legacy_reason='SIGNAL_REVERSE' engine_reason='ADVERSE' explanation='' legacy_net=295.76 engine_net=-78.79 legacy_mae=1.40 engine_mae=0.76
2 ENGINE_ONLY APP sig_position_fixture_v1 1774532400042270317 2 legacy_side=None engine_side=LONG legacy_reason='' engine_reason='ADVERSE' explanation='LEGACY_IN_POSITION' legacy_net=None engine_net=-54.34 legacy_mae=None engine_mae=0.38
3 ENTRY_CHANGED APP sig_position_fixture_v1 1774532640080820592 3 legacy_side=SHORT engine_side=SHORT legacy_reason='SIGNAL_REVERSE' engine_reason='ADVERSE' explanation='' legacy_net=-212.57 engine_net=-32.67 legacy_mae=4.39 engine_mae=0.21
4 ENTRY_CHANGED APP sig_position_fixture_v1 1774533840156975668 8 legacy_side=LONG engine_side=LONG legacy_reason='SIGNAL_REVERSE' engine_reason='ADVERSE' explanation='' legacy_net=6.62 engine_net=-24.54 legacy_mae=2.53 engine_mae=0.23
5 ENTRY_CHANGED APP sig_position_fixture_v1 1774534320718523255 10 legacy_side=LONG engine_side=LONG legacy_reason='SIGNAL_REVERSE' engine_reason='ADVERSE' explanation='' legacy_net=-122.61 engine_net=-35.81 legacy_mae=2.48 engine_mae=0.87
6 ENGINE_ONLY APP sig_position_fixture_v1 1774534560012760775 11 legacy_side=None engine_side=SHORT legacy_reason='' engine_reason='ADVERSE' explanation='LEGACY_IN_POSITION' legacy_net=None engine_net=-51.73 legacy_mae=None engine_mae=0.16
7 ENTRY_CHANGED APP sig_position_fixture_v1 1774534800516439309 12 legacy_side=LONG engine_side=LONG legacy_reason='SIGNAL_REVERSE' engine_reason='ADVERSE' explanation='' legacy_net=179.11 engine_net=-58.77 legacy_mae=0.50 engine_mae=0.20
8 ENGINE_ONLY APP sig_position_fixture_v1 1774535040072290942 13 legacy_side=None engine_side=SHORT legacy_reason='' engine_reason='ADVERSE' explanation='LEGACY_IN_POSITION' legacy_net=None engine_net=-32.69 legacy_mae=None engine_mae=0.33
9 ENTRY_CHANGED APP sig_position_fixture_v1 1774535520801766552 15 legacy_side=SHORT engine_side=SHORT legacy_reason='SIGNAL_REVERSE' engine_reason='ADVERSE' explanation='' legacy_net=10.71 engine_net=-47.41 legacy_mae=0.32 engine_mae=0.32
10 ENTRY_CHANGED APP sig_position_fixture_v1 1774536000010077241 17 legacy_side=SHORT engine_side=SHORT legacy_reason='SIGNAL_REVERSE' engine_reason='HORIZON' explanation='' legacy_net=105.86 engine_net=82.42 legacy_mae=0.0936507936507936507936508 engine_mae=0.0936507936507936507936508
11 ENTRY_CHANGED APP sig_position_fixture_v1 1774536720123576162 20 legacy_side=LONG engine_side=LONG legacy_reason='SIGNAL_REVERSE' engine_reason='ADVERSE' explanation='' legacy_net=9.46 engine_net=-27.34 legacy_mae=0.58 engine_mae=0.20
12 ENGINE_ONLY APP sig_position_fixture_v1 1774536960349460564 21 legacy_side=None engine_side=SHORT legacy_reason='' engine_reason='ADVERSE' explanation='LEGACY_IN_POSITION' legacy_net=None engine_net=-32.54 legacy_mae=None engine_mae=0.30
13 ENTRY_CHANGED APP sig_position_fixture_v1 1774537200029682535 22 legacy_side=LONG engine_side=LONG legacy_reason='SIGNAL_REVERSE' engine_reason='ADVERSE' explanation='' legacy_net=-12.67 engine_net=-81.75 legacy_mae=1.03 engine_mae=0.59
14 ENGINE_ONLY APP sig_position_fixture_v1 1774537440188947343 23 legacy_side=None engine_side=SHORT legacy_reason='' engine_reason='ADVERSE' explanation='LEGACY_IN_POSITION' legacy_net=None engine_net=-38.01 legacy_mae=None engine_mae=0.12
15 ENTRY_CHANGED APP sig_position_fixture_v1 1774537680777808531 24 legacy_side=LONG engine_side=LONG legacy_reason='SIGNAL_REVERSE' engine_reason='ADVERSE' explanation='' legacy_net=-98.57 engine_net=-31.92 legacy_mae=2.00 engine_mae=0.06
16 ENGINE_ONLY APP sig_position_fixture_v1 1774538160204603065 26 legacy_side=None engine_side=LONG legacy_reason='' engine_reason='ADVERSE' explanation='LEGACY_IN_POSITION' legacy_net=None engine_net=-20.65 legacy_mae=None engine_mae=0.15
17 ENGINE_ONLY APP sig_position_fixture_v1 1774538400879330462 27 legacy_side=None engine_side=SHORT legacy_reason='' engine_reason='ADVERSE' explanation='LEGACY_IN_POSITION' legacy_net=None engine_net=-35.10 legacy_mae=None engine_mae=0.29
18 ENTRY_CHANGED APP sig_position_fixture_v1 1774538640162658913 28 legacy_side=LONG engine_side=LONG legacy_reason='SIGNAL_REVERSE' engine_reason='ADVERSE' explanation='' legacy_net=119.44 engine_net=-27.51 legacy_mae=0.17 engine_mae=0.17
19 ENGINE_ONLY APP sig_position_fixture_v1 1774538880626263612 29 legacy_side=None engine_side=SHORT legacy_reason='' engine_reason='ADVERSE' explanation='LEGACY_IN_POSITION' legacy_net=None engine_net=-35.22 legacy_mae=None engine_mae=0.20
20 LEGACY_ONLY APP sig_position_fixture_v1 1774539120314535352 30 legacy_side=LONG engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='NO_ORDER:resting_order_guard_blocked_duplicate_passive_order' legacy_net=10.51 engine_net=None legacy_mae=0.40 engine_mae=None
21 ENGINE_ONLY APP sig_position_fixture_v1 1774540320174432459 35 legacy_side=None engine_side=SHORT legacy_reason='' engine_reason='ADVERSE' explanation='NO_ORDER:resting_order_guard_blocked_duplicate_passive_order' legacy_net=None engine_net=-43.89 legacy_mae=None engine_mae=0.35
22 ENGINE_ONLY APP sig_position_fixture_v1 1774541040611792967 38 legacy_side=None engine_side=LONG legacy_reason='' engine_reason='ADVERSE' explanation='NO_ORDER:resting_order_guard_blocked_duplicate_passive_order' legacy_net=None engine_net=-46.64 legacy_mae=None engine_mae=0.51
23 ENGINE_ONLY APP sig_position_fixture_v1 1774541520080823989 40 legacy_side=None engine_side=LONG legacy_reason='' engine_reason='ADVERSE' explanation='NO_ORDER:resting_order_guard_blocked_duplicate_passive_order' legacy_net=None engine_net=-30.03 legacy_mae=None engine_mae=0.21
24 ENGINE_ONLY APP sig_position_fixture_v1 1774541761196131867 41 legacy_side=None engine_side=SHORT legacy_reason='' engine_reason='ADVERSE' explanation='NO_ORDER:resting_order_guard_blocked_duplicate_passive_order' legacy_net=None engine_net=-54.69 legacy_mae=None engine_mae=1.05
25 ENGINE_ONLY APP sig_position_fixture_v1 1774542000493018777 42 legacy_side=None engine_side=LONG legacy_reason='' engine_reason='ADVERSE' explanation='NO_ORDER:resting_order_guard_blocked_duplicate_passive_order' legacy_net=None engine_net=-28.63 legacy_mae=None engine_mae=0.20
26 ENGINE_ONLY APP sig_position_fixture_v1 1774542241148145773 43 legacy_side=None engine_side=SHORT legacy_reason='' engine_reason='HORIZON' explanation='NO_ORDER:resting_order_guard_blocked_duplicate_passive_order' legacy_net=None engine_net=1.46 legacy_mae=None engine_mae=0.01
27 ENGINE_ONLY APP sig_position_fixture_v1 1774542481099535176 44 legacy_side=None engine_side=LONG legacy_reason='' engine_reason='ADVERSE' explanation='NO_ORDER:resting_order_guard_blocked_duplicate_passive_order' legacy_net=None engine_net=-43.68 legacy_mae=None engine_mae=0.19
28 ENTRY_CHANGED APP sig_position_fixture_v1 1774542720060485000 45 legacy_side=SHORT engine_side=SHORT legacy_reason='SIGNAL_REVERSE' engine_reason='ADVERSE' explanation='' legacy_net=-66.69 engine_net=4.25 legacy_mae=1.32 engine_mae=0.73
29 ENGINE_ONLY APP sig_position_fixture_v1 1774542960932787506 46 legacy_side=None engine_side=LONG legacy_reason='' engine_reason='ADVERSE' explanation='LEGACY_IN_POSITION' legacy_net=None engine_net=-72.26 legacy_mae=None engine_mae=0.76
30 ENTRY_CHANGED APP sig_position_fixture_v1 1774543440616483936 48 legacy_side=LONG engine_side=LONG legacy_reason='SIGNAL_REVERSE' engine_reason='ADVERSE' explanation='' legacy_net=-6.82 engine_net=-16.27 legacy_mae=0.40 engine_mae=0
31 ENGINE_ONLY APP sig_position_fixture_v1 1774543680808787362 49 legacy_side=None engine_side=SHORT legacy_reason='' engine_reason='ADVERSE' explanation='LEGACY_IN_POSITION' legacy_net=None engine_net=-17.04 legacy_mae=None engine_mae=0
32 ENTRY_CHANGED APP sig_position_fixture_v1 1774543920555117377 50 legacy_side=LONG engine_side=LONG legacy_reason='SIGNAL_REVERSE' engine_reason='ADVERSE' explanation='' legacy_net=-57.41 engine_net=-59.46 legacy_mae=1.22 engine_mae=0.37
33 ENGINE_ONLY APP sig_position_fixture_v1 1774544162519864531 51 legacy_side=None engine_side=SHORT legacy_reason='' engine_reason='ADVERSE' explanation='LEGACY_IN_POSITION' legacy_net=None engine_net=-138.41 legacy_mae=None engine_mae=1.20
34 ENTRY_CHANGED APP sig_position_fixture_v1 1774544400003284158 52 legacy_side=LONG engine_side=LONG legacy_reason='SIGNAL_REVERSE' engine_reason='ADVERSE' explanation='' legacy_net=-5.40 engine_net=-38.96 legacy_mae=0.54 engine_mae=0.14
35 ENGINE_ONLY APP sig_position_fixture_v1 1774545360546657704 56 legacy_side=None engine_side=LONG legacy_reason='' engine_reason='ADVERSE' explanation='LEGACY_IN_POSITION' legacy_net=None engine_net=-72.53 legacy_mae=None engine_mae=0.64
36 LEGACY_ONLY APP sig_position_fixture_v1 1774546080037101237 59 legacy_side=SHORT engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' legacy_net=-4.65 engine_net=None legacy_mae=1.12 engine_mae=None
37 LEGACY_ONLY APP sig_position_fixture_v1 1774546561293344960 61 legacy_side=SHORT engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' legacy_net=-7.93 engine_net=None legacy_mae=1.39 engine_mae=None
38 LEGACY_ONLY APP sig_position_fixture_v1 1774547040845371844 63 legacy_side=SHORT engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' legacy_net=107.26 engine_net=None legacy_mae=0.19 engine_mae=None
39 LEGACY_ONLY APP sig_position_fixture_v1 1774548000006155928 67 legacy_side=SHORT engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' legacy_net=76.73 engine_net=None legacy_mae=0.70 engine_mae=None
40 LEGACY_ONLY APP sig_position_fixture_v1 1774548480217489334 69 legacy_side=SHORT engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' legacy_net=-50.74 engine_net=None legacy_mae=0.89 engine_mae=None
41 LEGACY_ONLY APP sig_position_fixture_v1 1774548960072510644 71 legacy_side=SHORT engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' legacy_net=12.75 engine_net=None legacy_mae=0.28 engine_mae=None
42 LEGACY_ONLY APP sig_position_fixture_v1 1774549440044107203 73 legacy_side=SHORT engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' legacy_net=-1.77 engine_net=None legacy_mae=0.83 engine_mae=None
43 LEGACY_ONLY APP sig_position_fixture_v1 1774549921320657334 75 legacy_side=SHORT engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' legacy_net=-138.20 engine_net=None legacy_mae=2.05 engine_mae=None
44 LEGACY_ONLY APP sig_position_fixture_v1 1774550400249610864 77 legacy_side=SHORT engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' legacy_net=-7.31 engine_net=None legacy_mae=0.43 engine_mae=None
45 LEGACY_ONLY APP sig_position_fixture_v1 1774550880391575490 79 legacy_side=SHORT engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' legacy_net=-63.34 engine_net=None legacy_mae=1.26 engine_mae=None
46 LEGACY_ONLY APP sig_position_fixture_v1 1774551360008482384 81 legacy_side=SHORT engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' legacy_net=-86.87 engine_net=None legacy_mae=1.64 engine_mae=None
47 LEGACY_ONLY APP sig_position_fixture_v1 1774551841777673764 83 legacy_side=SHORT engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' legacy_net=-12.40 engine_net=None legacy_mae=0.49 engine_mae=None
48 LEGACY_ONLY APP sig_position_fixture_v1 1774552320723832836 85 legacy_side=SHORT engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' legacy_net=12.74 engine_net=None legacy_mae=0.39 engine_mae=None
49 LEGACY_ONLY APP sig_position_fixture_v1 1774552800287771041 87 legacy_side=SHORT engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' legacy_net=-29.48 engine_net=None legacy_mae=0.99 engine_mae=None
50 LEGACY_ONLY APP sig_position_fixture_v1 1774553280079049514 89 legacy_side=SHORT engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' legacy_net=-26.71 engine_net=None legacy_mae=1.57 engine_mae=None
51 LEGACY_ONLY APP sig_position_fixture_v1 1774553760382993295 91 legacy_side=SHORT engine_side=None legacy_reason='SIGNAL_REVERSE' engine_reason='' explanation='RISK:per-alpha drawdown 5.28% >= limit 5.0% — alpha should be quarantined' legacy_net=55.54 engine_net=None legacy_mae=0.25 engine_mae=None
