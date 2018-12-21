import argparse
import os
import json
import numpy as np
import open3d
import time

from dataset.kitti_dataset import KittiDataset
from predict import PredictInterpolator


def interpolate_dense_labels(sparse_points, sparse_labels, dense_points, k=3):
    sparse_pcd = open3d.PointCloud()
    sparse_pcd.points = open3d.Vector3dVector(sparse_points)
    sparse_pcd_tree = open3d.KDTreeFlann(sparse_pcd)

    dense_labels = []
    for dense_point in dense_points:
        result_k, sparse_indexes, _ = sparse_pcd_tree.search_knn_vector_3d(
            dense_point, k
        )
        knn_sparse_labels = sparse_labels[sparse_indexes]
        dense_label = np.bincount(knn_sparse_labels).argmax()
        dense_labels.append(dense_label)
    return dense_labels


if __name__ == "__main__":
    np.random.seed(0)

    # Parser
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--num_samples",
        type=int,
        default=8,
        help="# samples, each contains num_point points",
    )
    parser.add_argument("--ckpt", default="", help="Checkpoint file")
    parser.add_argument('--save', action="store_true", default=False)
    flags = parser.parse_args()
    hyper_params = json.loads(open("semantic_no_color.json").read())

    # Create output dir
    sparse_output_dir = os.path.join("result", "sparse")
    dense_output_dir = os.path.join("result", "dense")
    os.makedirs(sparse_output_dir, exist_ok=True)
    os.makedirs(dense_output_dir, exist_ok=True)

    # Dataset
    dataset = KittiDataset(
        num_points_per_sample=hyper_params["num_point"],
        base_dir="/home/ylao/data/kitti",
        dates=["2011_09_26"],
        # drives=["0095", "0001"],
        drives=["0095"],
        box_size_x=hyper_params["box_size_x"],
        box_size_y=hyper_params["box_size_y"],
    )

    # Model
    max_batch_size = 128  # The more the better, limited by memory size
    predictor = PredictInterpolator(
        checkpoint_path=flags.ckpt,
        num_classes=dataset.num_classes,
        hyper_params=hyper_params,
    )

    # Init visualizer
    dense_pcd = open3d.PointCloud()
    vis = open3d.Visualizer()
    vis.create_window()
    vis.add_geometry(dense_pcd)
    render_option = vis.get_render_option()
    render_option.point_size = 0.05

    for kitti_file_data in dataset.list_file_data[:5]:
        timer = {"load_data": 0, "predict_interpolate": 0, "write_data": 0}

        # Predict for num_samples times
        points_collector = []
        pd_labels_collector = []

        # Get data
        start_time = time.time()
        points_centered, points = kitti_file_data.get_batch_of_one_z_box_from_origin(
            num_points_per_sample=hyper_params["num_point"]
        )
        if len(points_centered) > max_batch_size:
            raise NotImplementedError("TODO: iterate batches if > max_batch_size")
        timer["load_data"] += time.time() - start_time

        # Predict and interpolate
        start_time = time.time()
        dense_points = kitti_file_data.points
        dense_labels = predictor.predict_and_interpolate(
            sparse_points_centered_batched=points_centered,  # (batch_size, num_sparse_points, 3)
            sparse_points_batched=points,  # (batch_size, num_sparse_points, 3)
            dense_points=dense_points,  # (num_dense_points, 3)
        )
        timer["predict_interpolate"] += time.time() - start_time

        # Save dense point cloud with predicted labels
        if flags.save:
            start_time = time.time()
            file_prefix = os.path.basename(kitti_file_data.file_path_without_ext)

            dense_pcd = open3d.PointCloud()
            dense_pcd.points = open3d.Vector3dVector(dense_points.reshape((-1, 3)))
            dense_pcd_path = os.path.join(dense_output_dir, file_prefix + ".pcd")
            open3d.write_point_cloud(dense_pcd_path, dense_pcd)
            print("Exported dense_pcd to {}".format(dense_pcd_path))

            dense_labels_path = os.path.join(dense_output_dir, file_prefix + ".labels")
            np.savetxt(dense_labels_path, dense_labels, fmt="%d")
            print("Exported dense_labels to {}".format(dense_labels_path))
            timer["write_data"] += time.time() - start_time

        print(timer)
