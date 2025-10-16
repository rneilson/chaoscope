from pathlib import Path
from typing import Generator

import numpy as np
from matplotlib import pyplot as plt
from matplotlib.figure import Figure

BASE_DIR = Path(__file__).parent.resolve()
RAW_MAG_FILE = BASE_DIR / "raw_mag.txt"
CAL_MAG_FILE = BASE_DIR / "cal_mag.txt"
PLT_IMG_FILE_TMPL = "calibration-{}.png"


def plot_data(data: np.ndarray, title: str) -> Generator[Figure, None, None]:
    """
    Plot magnetometer data with 3D trajectory and projections.

    Adapted from:
    https://github.com/nliaudat/magnetometer_calibration/blob/main/calibrate.py
    """

    alpha = 1  # Transparency for scatter plots
    s = 2  # Size of scatter points

    # 3D trajectory
    fig_3d = plt.figure(figsize=(8, 5))
    ax1 = fig_3d.add_subplot(111, projection="3d")
    ax1.plot(data[:, 0], data[:, 1], data[:, 2])
    ax1.set_title(f"{title} Magnetometer Trajectory 3D")
    ax1.set_xlabel("X (µT)")
    ax1.set_ylabel("Y (µT)")
    ax1.set_zlabel("Z (µT)")
    ax1.set_aspect("equal")

    yield fig_3d

    # Calculate limits for consistent scaling
    min_val = np.min(data)
    max_val = np.max(data)

    # Projections figure
    fig_proj = plt.figure(figsize=(16, 4))

    # XY projection
    ax_xy = fig_proj.add_subplot(141)
    ax_xy.scatter(data[:, 0], data[:, 1], alpha=alpha, c="red", label="XY plane", s=s)
    ax_xy.set_title(f"{title} Magnetometer XY Projection")
    ax_xy.set_xlabel("X (µT)")
    ax_xy.set_ylabel("Y (µT)")
    ax_xy.set_xlim([min_val, max_val])
    ax_xy.set_ylim([min_val, max_val])
    ax_xy.set_aspect("equal")
    ax_xy.grid(True)
    ax_xy.legend()

    # XZ projection
    ax_xz = fig_proj.add_subplot(142)
    ax_xz.scatter(data[:, 0], data[:, 2], alpha=alpha, c="green", label="XZ plane", s=s)
    ax_xz.set_title(f"{title} Magnetometer XZ Projection")
    ax_xz.set_xlabel("X (µT)")
    ax_xz.set_ylabel("Z (µT)")
    ax_xz.set_xlim([min_val, max_val])
    ax_xz.set_ylim([min_val, max_val])
    ax_xz.set_aspect("equal")
    ax_xz.grid(True)
    ax_xz.legend()

    # YZ projection
    ax_yz = fig_proj.add_subplot(143)
    ax_yz.scatter(data[:, 1], data[:, 2], alpha=alpha, c="blue", label="YZ plane", s=s)
    ax_yz.set_title(f"{title} Magnetometer YZ Projection")
    ax_yz.set_xlabel("Y (µT)")
    ax_yz.set_ylabel("Z (µT)")
    ax_yz.set_xlim([min_val, max_val])
    ax_yz.set_ylim([min_val, max_val])
    ax_yz.set_aspect("equal")
    ax_yz.grid(True)
    ax_yz.legend()

    # Combined XYZ projection
    ax_xyz = fig_proj.add_subplot(144)
    ax_xyz.scatter(data[:, 0], data[:, 1], alpha=alpha, c="red", label="XY plane", s=s)
    ax_xyz.scatter(
        data[:, 0], data[:, 2], alpha=alpha, c="green", label="XZ plane", s=s
    )
    ax_xyz.scatter(data[:, 1], data[:, 2], alpha=alpha, c="blue", label="YZ plane", s=s)
    ax_xyz.set_title(f"{title} Magnetometer XYZ Combined")
    ax_xyz.set_xlabel("Coordinate (µT)")
    ax_xyz.set_ylabel("Coordinate (µT)")
    ax_xyz.set_xlim([min_val, max_val])
    ax_xyz.set_ylim([min_val, max_val])
    ax_xyz.set_aspect("equal")
    ax_xyz.grid(True)
    ax_xyz.legend()

    plt.tight_layout()

    yield fig_proj


def main():
    # TODO: make files configurable via args
    print("Loading data...")
    raw_data = np.loadtxt(RAW_MAG_FILE, delimiter=",")
    calibrated_data = np.loadtxt(CAL_MAG_FILE, delimiter=",")

    print("Plotting data...")

    i = 0

    def print_figure(fig: Figure):
        nonlocal i
        i += 1
        filename = BASE_DIR / PLT_IMG_FILE_TMPL.format(i)
        print(f"Saving {filename}...")
        fig.savefig(filename)

    for fig in plot_data(raw_data, "Raw"):
        print_figure(fig)

    for fig in plot_data(calibrated_data, "Calibrated"):
        print_figure(fig)


if __name__ == "__main__":
    main()
