import colorsys
import os
import time
from pathlib import Path
import numpy as np
import torch
import torch.nn as nn
from PIL import ImageDraw, ImageFont

from .lib.tools import cvtColor, get_anchors, get_classes, preprocess_input,resize_image, check_suffix
from .lib.decodebox import DecodeBox


class YOLOV7(object):
    def __init__(self, **kwargs):
        self._params = {
            "model_path" : kwargs['model_path'], 
            "classes_path" : kwargs['class_path'], 
            "anchors_path" : kwargs['anchors_path'], 
            "anchors_mask" : [[6, 7, 8], [3, 4, 5], [0, 1, 2]],
            "input_shape" : kwargs['input_shape'],
            "phi" : kwargs['phi'],
            "confidence" : kwargs['confidence'], 
            "nms_iou" : kwargs['nms_iou'],
            "max_boxes" : kwargs['max_boxes'], 
            "letterbox_image" : kwargs['letterbox_image'],
            "tiny":kwargs['tiny'],
            "cuda":kwargs['cuda']
        }
        self.__dict__.update(self._params)
            
        self.class_names, self.num_classes  = get_classes(self.classes_path)
        self.anchors, self.num_anchors = get_anchors(self.anchors_path)
        self.bbox_util = DecodeBox(self.anchors, self.num_classes, (self.input_shape[0], self.input_shape[1]), self.anchors_mask)

        hsv_tuples = [(x / self.num_classes, 1., 1.) for x in range(self.num_classes)]
        self.colors = list(map(lambda x: colorsys.hsv_to_rgb(*x), hsv_tuples))
        self.colors = list(map(lambda x: (int(x[0] * 255), int(x[1] * 255), int(x[2] * 255)), self.colors))
        self.init_model()

    def init_model(self):
        # 加载不同类型的模型
        weights = str(self.model_path[0] if isinstance(self.model_path, list) else self.model_path)
        suffix, suffixes = Path(weights).suffix.lower(), ['.pth', '.onnx']
        # check weights have acceptable suffix
        check_suffix(weights, suffixes)
        # backbend booleans
        self.pt, self.onnx = (suffix==x for x in suffixes)
        if self.tiny:
            from .nets.yolov7_tiny import YoloBody
        else:
            from .nets.yolov7 import YoloBody
        if self.pt:
            self.net = YoloBody(self.anchors_mask, self.num_classes, phi = self.phi)
            device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
            self.net.load_state_dict(torch.load(self.model_path, map_location=device))
            self.net = self.net.fuse().eval()
            print('{} model, and classes loaded.'.format(self.model_path))
            if self.cuda:
                self.net = nn.DataParallel(self.net)
                self.net = self.net.cuda()
        if self.onnx:
            import onnxruntime
            print('Init ONNX model')
            self.net = onnxruntime.InferenceSession(weights, None)

    def detect(self, image, crop = False, istrack=False):
        image_shape = np.array(np.shape(image)[0:2])
        image = cvtColor(image)
        image_data  = resize_image(image, (self.input_shape[1], self.input_shape[0]), self.letterbox_image)
        image_data  = np.expand_dims(np.transpose(preprocess_input(np.array(image_data, dtype='float32')), (2, 0, 1)), 0)
        # 推理
        if self.pt:
            with torch.no_grad():
                images = torch.from_numpy(image_data)
                if self.cuda:
                    images = images.cuda()
                outputs = self.net(images)
        if self.onnx:
            print('ONNNX Inference...')
            outputs = torch.tensor(self.net.run([self.net.get_outputs()[0].name], {self.net.get_inputs()[0].name: image_data}))

        # 后处理
        outputs = self.bbox_util.decode_box(outputs)
        results = self.bbox_util.non_max_suppression(torch.cat(outputs, 1), self.num_classes, self.input_shape, 
                    image_shape, self.letterbox_image, conf_thres = self.confidence, nms_thres = self.nms_iou)
                                                    
        if results[0] is None: 
            return image

        top_label = np.array(results[0][:, 6], dtype = 'int32')
        top_conf = results[0][:, 4] * results[0][:, 5]
        top_boxes = results[0][:, :4]

        # 结果展示
        font = ImageFont.truetype(font='./font/simhei.ttf', size=np.floor(3e-2 * image.size[1] + 0.5).astype('int32'))
        thickness   = int(max((image.size[0] + image.size[1]) // np.mean(self.input_shape), 1))
        if crop:
            for i, c in list(enumerate(top_boxes)):
                top, left, bottom, right = top_boxes[i]
                top     = max(0, np.floor(top).astype('int32'))
                left    = max(0, np.floor(left).astype('int32'))
                bottom  = min(image.size[1], np.floor(bottom).astype('int32'))
                right   = min(image.size[0], np.floor(right).astype('int32'))
                
                dir_save_path = "img_crop"
                if not os.path.exists(dir_save_path):
                    os.makedirs(dir_save_path)
                crop_image = image.crop([left, top, right, bottom])
                crop_image.save(os.path.join(dir_save_path, "crop_" + str(i) + ".png"), quality=95, subsampling=0)
                print("save crop_" + str(i) + ".png to " + dir_save_path)

        for i, c in list(enumerate(top_label)):
            predicted_class = self.class_names[int(c)]
            box = top_boxes[i]
            score = top_conf[i]

            top, left, bottom, right = box

            top = max(0, np.floor(top).astype('int32'))
            left    = max(0, np.floor(left).astype('int32'))
            bottom  = min(image.size[1], np.floor(bottom).astype('int32'))
            right   = min(image.size[0], np.floor(right).astype('int32'))

            label = '{} {:.2f}'.format(predicted_class, score)
            draw = ImageDraw.Draw(image)
            label_size = draw.textsize(label, font)
            label = label.encode('utf-8')
            print(label, top, left, bottom, right)
            
            if top - label_size[1] >= 0:
                text_origin = np.array([left, top - label_size[1]])
            else:
                text_origin = np.array([left, top + 1])

            for i in range(thickness):
                draw.rectangle([left + i, top + i, right - i, bottom - i], outline=self.colors[c])
            draw.rectangle([tuple(text_origin), tuple(text_origin + label_size)], fill=self.colors[c])
            draw.text(text_origin, str(label,'UTF-8'), fill=(0, 0, 0), font=font)
            del draw

        return image


    def detect_heatmap(self, image, heatmap_save_path):
        # TODO:headmap
        pass


def Inference_YOLOV7Model(config, model_path):
    yolo = YOLOV7(
        model_path = model_path,
        class_path = config.classes_path,
        anchors_path = config.anchors_path,
        anchors_mask = config.ANCHOR_MASK,
        input_shape = config.input_shape,
        confidence = config.score,
        nms_iou = config.iou,
        max_boxes=config.max_boxes,
        letterbox_image = True,
        phi=config.phi,
        tiny = config.tiny,
        cuda = config.cuda
    )
    return yolo
