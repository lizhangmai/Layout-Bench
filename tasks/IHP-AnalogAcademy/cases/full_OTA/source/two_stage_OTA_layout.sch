v {xschem version=3.4.6 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
N 450 -435 450 -395 {
lab=dn3}
N 450 -435 560 -435 {
lab=dn3}
N 660 -305 860 -305 {
lab=vss}
N 560 -365 620 -365 {
lab=dn3}
N 560 -435 560 -365 {
lab=dn3}
N 490 -365 560 -365 {
lab=dn3}
N 450 -495 450 -435 {
lab=dn3}
N 450 -525 660 -525 {
lab=bulk}
N 450 -575 450 -555 {
lab=dn2}
N 660 -575 660 -555 {
lab=dn2}
N 560 -575 660 -575 {
lab=dn2}
N 380 -525 410 -525 {
lab=v-}
N 700 -525 730 -525 {
lab=v+}
N 390 -625 520 -625 {
lab=iout}
N 170 -575 170 -555 {
lab=iout}
N 170 -575 220 -575 {
lab=iout}
N 220 -625 240 -625 {
lab=iout}
N 170 -595 170 -575 {
lab=iout}
N 220 -625 220 -575 {
lab=iout}
N 210 -625 220 -625 {
lab=iout}
N 800 -625 820 -625 {
lab=iout}
N 860 -525 900 -525 {
lab=vout}
N 860 -595 860 -525 {
lab=vout}
N 660 -400 660 -395 {
lab=dn4}
N 560 -675 860 -675 {
lab=vdd}
N 560 -595 560 -575 {
lab=dn2}
N 450 -575 560 -575 {
lab=dn2}
N 760 -400 820 -400 {
lab=dn4}
N 660 -495 660 -400 {
lab=dn4}
N 760 -460 760 -400 {
lab=dn4}
N 660 -400 760 -400 {
lab=dn4}
N 860 -460 860 -430 {
lab=vout}
N 820 -460 860 -460 {
lab=vout}
N 860 -525 860 -460 {
lab=vout}
N 230 -285 285 -285 {
lab=bulk}
N 190 -315 190 -285 {
lab=vdd}
N 230 -255 230 -235 {
lab=dn4}
N 75 -285 130 -285 {
lab=bulk}
N 35 -315 35 -285 {
lab=vdd}
N 75 -255 75 -235 {
lab=dn3}
N 660 -335 660 -305 {
lab=vss}
N 450 -305 660 -305 {
lab=vss}
N 450 -335 450 -305 {
lab=vss}
N 370 -365 450 -365 {
lab=bulk2}
N 660 -365 740 -365 {
lab=bulk2}
N 860 -375 860 -305 {
lab=vss}
N 860 -400 940 -400 {
lab=bulk2}
N 190 -315 230 -315 {
lab=vdd}
N 35 -315 75 -315 {
lab=vdd}
N 860 -675 860 -655 {
lab=vdd}
N 170 -675 170 -655 {
lab=vdd}
N 105 -625 170 -625 {
lab=bulk4}
N 860 -625 930 -625 {
lab=bulk4}
N 560 -675 560 -655 {
lab=vdd}
N 170 -675 560 -675 {
lab=vdd}
N 560 -625 630 -625 {
lab=bulk1}
N 230 -395 285 -395 {
lab=bulk}
N 190 -425 190 -395 {
lab=vdd}
N 230 -365 230 -345 {
lab=dn2}
N 75 -395 130 -395 {
lab=bulk}
N 35 -425 35 -395 {
lab=vdd}
N 75 -365 75 -345 {
lab=dn2}
N 190 -425 230 -425 {
lab=vdd}
N 35 -425 75 -425 {
lab=vdd}
C {sg13g2_pr/sg13_lv_nmos.sym} 640 -365 0 0 {name=M4
l=9.75u
w=720n
ng=1
m=1
model=sg13_lv_nmos
spiceprefix=X
}
C {sg13g2_pr/sg13_lv_nmos.sym} 470 -365 0 1 {name=M3
l=9.75u
w=720n
ng=1
m=1
model=sg13_lv_nmos
spiceprefix=X
}
C {sg13g2_pr/sg13_lv_pmos.sym} 430 -525 0 0 {name=M1
l=3.7u
w=3.64u
ng=1
m=2
model=sg13_lv_pmos
spiceprefix=X
}
C {sg13g2_pr/sg13_lv_pmos.sym} 680 -525 0 1 {name=M2
l=3.7u
w=3.64u
ng=1
m=2
model=sg13_lv_pmos
spiceprefix=X
}
C {sg13g2_pr/sg13_lv_pmos.sym} 540 -625 0 0 {name=M7
l=1.95u
w=5.3u
ng=1
m=1
model=sg13_lv_pmos
spiceprefix=X
}
C {sg13g2_pr/sg13_lv_pmos.sym} 840 -625 0 0 {name=M5
l=2.08u
w=75u
ng=8
m=1
model=sg13_lv_pmos
spiceprefix=X
}
C {sg13g2_pr/sg13_lv_nmos.sym} 840 -400 0 0 {name=M6
l=9.75u
w=28.8u
ng=4
m=1
model=sg13_lv_nmos
spiceprefix=X
}
C {iopin.sym} 380 -525 0 1 {name=p10 lab=v-}
C {iopin.sym} 730 -525 0 0 {name=p11 lab=v+}
C {iopin.sym} 560 -305 1 1 {name=p5 lab=vss}
C {iopin.sym} 455 -675 1 1 {name=p1 lab=vdd}
C {iopin.sym} 170 -555 0 1 {name=p3 lab=iout}
C {iopin.sym} 900 -525 0 0 {name=p8 lab=vout}
C {lab_pin.sym} 240 -625 0 1 {name=p7 sig_type=std_logic lab=iout}
C {lab_pin.sym} 800 -625 0 0 {name=p6 sig_type=std_logic lab=iout}
C {sg13g2_pr/sg13_lv_pmos.sym} 190 -625 0 1 {name=M9
l=2.08u
w=75u
ng=8
m=1
model=sg13_lv_pmos
spiceprefix=X
}
C {sg13g2_pr/cap_cmim.sym} 790 -460 3 0 {name=C2
model=cap_cmim
w=22.295e-6
l=22.295e-6
m=1
spiceprefix=X}
C {lab_pin.sym} 390 -625 0 0 {name=p4 sig_type=std_logic lab=iout}
C {lab_pin.sym} 450 -455 0 0 {name=p9 sig_type=std_logic lab=dn3}
C {lab_pin.sym} 660 -455 0 0 {name=p12 sig_type=std_logic lab=dn4}
C {sg13g2_pr/sg13_lv_pmos.sym} 210 -285 0 0 {name=M8
l=3.7u
w=3.64u
ng=1
m=2
model=sg13_lv_pmos
spiceprefix=X
}
C {lab_pin.sym} 190 -315 0 0 {name=p15 sig_type=std_logic lab=vdd}
C {sg13g2_pr/sg13_lv_pmos.sym} 55 -285 0 0 {name=M10
l=3.7u
w=3.64u
ng=1
m=2
model=sg13_lv_pmos
spiceprefix=X
}
C {lab_pin.sym} 35 -315 0 0 {name=p17 sig_type=std_logic lab=vdd}
C {lab_pin.sym} 740 -365 0 1 {name=p25 sig_type=std_logic lab=bulk2}
C {lab_pin.sym} 370 -365 0 0 {name=p26 sig_type=std_logic lab=bulk2}
C {lab_pin.sym} 940 -400 0 1 {name=p27 sig_type=std_logic lab=bulk2}
C {lab_pin.sym} 560 -525 3 0 {name=p2 sig_type=std_logic lab=bulk}
C {lab_pin.sym} 130 -285 0 1 {name=p32 sig_type=std_logic lab=bulk}
C {lab_pin.sym} 285 -285 0 1 {name=p33 sig_type=std_logic lab=bulk}
C {lab_pin.sym} 105 -625 0 0 {name=p36 sig_type=std_logic lab=bulk4}
C {lab_pin.sym} 930 -625 2 0 {name=p37 sig_type=std_logic lab=bulk4}
C {lab_pin.sym} 560 -585 0 1 {name=p40 sig_type=std_logic lab=dn2}
C {lab_pin.sym} 630 -625 2 0 {name=p41 sig_type=std_logic lab=bulk1}
C {lab_pin.sym} 75 -235 0 0 {name=p43 sig_type=std_logic lab=dn3}
C {lab_pin.sym} 230 -235 0 0 {name=p18 sig_type=std_logic lab=dn4}
C {sg13g2_pr/sg13_lv_pmos.sym} 210 -395 0 0 {name=M15
l=3.7u
w=3.64u
ng=1
m=2
model=sg13_lv_pmos
spiceprefix=X
}
C {lab_pin.sym} 190 -425 0 0 {name=p49 sig_type=std_logic lab=vdd}
C {sg13g2_pr/sg13_lv_pmos.sym} 55 -395 0 0 {name=M16
l=3.7u
w=3.64u
ng=1
m=2
model=sg13_lv_pmos
spiceprefix=X
}
C {lab_pin.sym} 35 -425 0 0 {name=p50 sig_type=std_logic lab=vdd}
C {lab_pin.sym} 130 -395 0 1 {name=p51 sig_type=std_logic lab=bulk}
C {lab_pin.sym} 285 -395 0 1 {name=p52 sig_type=std_logic lab=bulk}
C {lab_pin.sym} 75 -345 0 0 {name=p53 sig_type=std_logic lab=dn2}
C {lab_pin.sym} 230 -345 0 0 {name=p54 sig_type=std_logic lab=dn2}
T {Full OTA: schematic matched to the case reference layout
Derived from IHP AnalogAcademy; Apache-2.0.
Tap A/P describe active rings; see the case README.} 35 -820 0 0 0.3 0.3 {}
C {sg13g2_case/ntap_ap.sym} 1170 -625 2 0 {name=R1
model=ntap1
spiceprefix=X
A=28.1356e-12
P=181.52e-6
}
N 1170 -675 1170 -655 {lab=bulk}
C {lab_pin.sym} 1170 -675 0 0 {name=R1_well sig_type=std_logic lab=bulk}
N 1170 -575 1170 -595 {lab=vdd}
C {lab_pin.sym} 1170 -575 0 0 {name=R1_tie sig_type=std_logic lab=vdd}
C {sg13g2_case/ntap_ap.sym} 1170 -445 2 0 {name=R3
model=ntap1
spiceprefix=X
A=6.9626e-12
P=44.92e-6
}
N 1170 -495 1170 -475 {lab=bulk1}
C {lab_pin.sym} 1170 -495 0 0 {name=R3_well sig_type=std_logic lab=bulk1}
N 1170 -395 1170 -415 {lab=vdd}
C {lab_pin.sym} 1170 -395 0 0 {name=R3_tie sig_type=std_logic lab=vdd}
C {sg13g2_case/ntap_ap.sym} 1170 -265 2 0 {name=R5
model=ntap1
spiceprefix=X
A=26.815e-12
P=173e-6
}
N 1170 -315 1170 -295 {lab=bulk4}
C {lab_pin.sym} 1170 -315 0 0 {name=R5_well sig_type=std_logic lab=bulk4}
N 1170 -215 1170 -235 {lab=vdd}
C {lab_pin.sym} 1170 -215 0 0 {name=R5_tie sig_type=std_logic lab=vdd}
C {sg13g2_case/ptap_ap.sym} 1450 -625 2 0 {name=R2
model=ptap1
spiceprefix=X
A=8.559e-12
P=57.06e-6
}
N 1450 -675 1450 -655 {lab=bulk2}
C {lab_pin.sym} 1450 -675 0 0 {name=R2_well sig_type=std_logic lab=bulk2}
N 1450 -575 1450 -595 {lab=vss}
C {lab_pin.sym} 1450 -575 0 0 {name=R2_tie sig_type=std_logic lab=vss}
C {sg13g2_case/ptap_ap.sym} 1450 -445 2 0 {name=R4
model=ptap1
spiceprefix=X
A=30.288e-12
P=201.92e-6
}
N 1450 -495 1450 -475 {lab=bulk2}
C {lab_pin.sym} 1450 -495 0 0 {name=R4_well sig_type=std_logic lab=bulk2}
N 1450 -395 1450 -415 {lab=vss}
C {lab_pin.sym} 1450 -395 0 0 {name=R4_tie sig_type=std_logic lab=vss}
