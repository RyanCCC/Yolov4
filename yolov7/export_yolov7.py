from cfg import YOLOV7Config
import os
import tensorflow as tf
import tf2onnx
import numpy as np
from .predict_yolov7 import Inference_YOLOV7Model


def export_model(weights, saved_pb, saved_pb_dir, opset, onnx_save_path):
    model_path = os.path.expanduser(weights)
    assert model_path.endswith('.h5'), 'Tensorflow model or weights must be a .h5 file.'
    yolo_model = Inference_YOLOV7Model(YOLOV7Config, weights).model
    yolo_model.compile()
    if saved_pb:
        assert len(saved_pb_dir) > 0, 'save_name cannot be none or empty.'
        yolo_model.save(saved_pb_dir, save_format='tf')
    model_proto, _ = tf2onnx.convert.from_keras(yolo_model, opset=opset, output_path=onnx_save_path)
    output_names = [n.name for n in model_proto.graph.output]
    print(f'Model output names: ',output_names)