v {xschem version=3.4.7 file_version=1.2
* SPDX-License-Identifier: Apache-2.0
* Layout-Bench derivative of TO_Apr2025 DC_to_130_GHz_TIA design_1.
* Source commit: 63e203a0eccfb6028a1a0a8364553e4e979b55b3.
* Redrawn in Xschem with current PDK symbols; independent supplies,
* explicit VEE resistor substrates and measured physical tap geometry.
* Intended supply decoupling is preserved; original GDS is not LVS-matched.
}
G {}
K {}
V {}
S {}
E {}
T {DC-130 GHz TIA design 1 -- editable core derivative} 100 -30 0 0 0.4 0.4 {}
T {Two independent supplies; intended supply decoupling. Original GDS requires investigation.} 100 10 0 0 0.25 0.25 {}
C {iopin.sym} 100 80 0 0 {name=p1 lab=INPUT}
C {iopin.sym} 330 80 0 0 {name=p2 lab=OUTPUT}
C {iopin.sym} 560 80 0 0 {name=p3 lab=VCC2V}
C {iopin.sym} 790 80 0 0 {name=p4 lab=VCC2V1}
C {iopin.sym} 1020 80 0 0 {name=p5 lab=VEE}
C {sg13g2_pr/npn13G2.sym} 400 400 0 0 {name=Q1 model=npn13G2 spiceprefix=X Nx=5 mm_ok=0}
C {sg13g2_pr/npn13G2.sym} 800 400 0 0 {name=Q2 model=npn13G2 spiceprefix=X Nx=4 mm_ok=0}
C {sg13g2_case/rppd_lvs.sym} 420 250 0 0 {name=RC1 model=rppd spiceprefix=X w=15u l=4u body=VEE b=0 m=1 mm_ok=0}
N 420 180 420 220 {lab=VCC2V}
C {lab_pin.sym} 420 180 0 0 {name=RC1s lab=VCC2V}
N 420 280 420 370 {lab=DN1}
C {lab_pin.sym} 420 340 0 0 {name=RC1n lab=DN1}
C {sg13g2_case/rppd_lvs.sym} 820 250 0 0 {name=RC2 model=rppd spiceprefix=X w=11.5u l=2u body=VEE b=0 m=1 mm_ok=0}
N 820 180 820 220 {lab=VCC2V1}
C {lab_pin.sym} 820 180 0 0 {name=RC2s lab=VCC2V1}
N 820 280 820 370 {lab=OUTPUT}
C {lab_pin.sym} 820 340 0 0 {name=RC2n lab=OUTPUT}
N 420 340 700 340 {lab=DN1}
N 700 340 700 400 {lab=DN1}
N 700 400 780 400 {lab=DN1}
N 180 400 380 400 {lab=INPUT}
C {lab_pin.sym} 180 400 0 0 {name=in lab=INPUT}
C {sg13g2_case/rppd_lvs.sym} 220 300 0 0 {name=RF model=rppd spiceprefix=X w=29u l=6.3u body=VEE b=0 m=1 mm_ok=0}
N 220 330 220 400 {lab=INPUT}
N 220 250 220 270 {lab=DN1}
C {lab_pin.sym} 220 250 0 0 {name=rf_top lab=DN1}
N 420 430 420 500 {lab=VEE}
N 420 400 510 400 {lab=VEE}
N 510 400 510 500 {lab=VEE}
N 420 500 510 500 {lab=VEE}
C {lab_pin.sym} 420 500 0 0 {name=vee420 lab=VEE}
N 820 430 820 500 {lab=VEE}
N 820 400 910 400 {lab=VEE}
N 910 400 910 500 {lab=VEE}
N 820 500 910 500 {lab=VEE}
C {lab_pin.sym} 820 500 0 0 {name=vee820 lab=VEE}
C {sg13g2_pr/cap_cmim.sym} 1100 250 0 0 {name=C1 model=cap_cmim spiceprefix=X w=30u l=30u m=1 mm_ok=0}
N 1100 180 1100 220 {lab=VCC2V}
C {lab_pin.sym} 1100 180 0 0 {name=C1top lab=VCC2V}
N 1100 280 1100 320 {lab=VEE}
C {lab_pin.sym} 1100 320 0 0 {name=C1bottom lab=VEE}
C {sg13g2_pr/cap_cmim.sym} 1400 250 0 0 {name=C2 model=cap_cmim spiceprefix=X w=30u l=30u m=1 mm_ok=0}
N 1400 180 1400 220 {lab=VCC2V1}
C {lab_pin.sym} 1400 180 0 0 {name=C2top lab=VCC2V1}
N 1400 280 1400 320 {lab=VEE}
C {lab_pin.sym} 1400 320 0 0 {name=C2bottom lab=VEE}
C {sg13g2_case/ptap_ap.sym} 1100 460 0 0 {name=RTAP model=ptap1 spiceprefix=X A=3.6504e-12 P=18.72e-6}
C {lab_pin.sym} 1100 430 0 0 {name=tap_tie lab=VEE}
C {lab_pin.sym} 1100 490 0 0 {name=tap_sub lab=VEE}
