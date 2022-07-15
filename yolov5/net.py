from tensorflow.keras.layers import Concatenate, Input, Lambda, UpSampling2D, ZeroPadding2D
from tensorflow.keras.models import Model
from nets.CSPdarknet_yolov5 import C3, darknet_body
from nets.CSPdarknet53 import DarknetConv2D_BN_SiLU, DarknetConv2D_withL2
from .loss import yolo_loss

# 构建网络
def yolo_body(input_shape, anchors_mask, num_classes, phi, weight_decay=5e-4):
    depth_dict          = {'n': 0.33, 's' : 0.33, 'm' : 0.67, 'l' : 1.00, 'x' : 1.33,}
    width_dict          = {'n': 0.25, 's' : 0.50, 'm' : 0.75, 'l' : 1.00, 'x' : 1.25,}
    dep_mul, wid_mul    = depth_dict[phi], width_dict[phi]

    base_channels       = int(wid_mul * 64)  # 64
    base_depth          = max(round(dep_mul * 3), 1)  # 3

    inputs      = Input(input_shape)
    feat1, feat2, feat3 = darknet_body(inputs, base_channels, base_depth, weight_decay)

    P5          = DarknetConv2D_BN_SiLU(int(base_channels * 8), (1, 1), weight_decay=weight_decay, name = 'conv_for_feat3')(feat3)  
    P5_upsample = UpSampling2D()(P5) 
    P5_upsample = Concatenate(axis = -1)([P5_upsample, feat2])
    P5_upsample = C3(P5_upsample, int(base_channels * 8), base_depth, shortcut = False, weight_decay=weight_decay, name = 'conv3_for_upsample1')

    P4          = DarknetConv2D_BN_SiLU(int(base_channels * 4), (1, 1), weight_decay=weight_decay, name = 'conv_for_feat2')(P5_upsample)
    P4_upsample = UpSampling2D()(P4)
    P4_upsample = Concatenate(axis = -1)([P4_upsample, feat1])
    P3_out      = C3(P4_upsample, int(base_channels * 4), base_depth, shortcut = False, weight_decay=weight_decay, name = 'conv3_for_upsample2')

    P3_downsample   = ZeroPadding2D(((1, 0),(1, 0)))(P3_out)
    P3_downsample   = DarknetConv2D_BN_SiLU(int(base_channels * 4), (3, 3), strides = (2, 2), weight_decay=weight_decay, name = 'down_sample1')(P3_downsample)
    P3_downsample   = Concatenate(axis = -1)([P3_downsample, P4])
    P4_out          = C3(P3_downsample, int(base_channels * 8), base_depth, shortcut = False, weight_decay=weight_decay, name = 'conv3_for_downsample1') 

    P4_downsample   = ZeroPadding2D(((1, 0),(1, 0)))(P4_out)
    P4_downsample   = DarknetConv2D_BN_SiLU(int(base_channels * 8), (3, 3), strides = (2, 2), weight_decay=weight_decay, name = 'down_sample2')(P4_downsample)
    P4_downsample   = Concatenate(axis = -1)([P4_downsample, P5])
    P5_out          = C3(P4_downsample, int(base_channels * 16), base_depth, shortcut = False, weight_decay=weight_decay, name = 'conv3_for_downsample2')

    out2 = DarknetConv2D_withL2(len(anchors_mask[2]) * (5 + num_classes), (1, 1), strides = (1, 1), weight_decay=weight_decay, name = 'yolo_head_P3')(P3_out)
    out1 = DarknetConv2D_withL2(len(anchors_mask[1]) * (5 + num_classes), (1, 1), strides = (1, 1), weight_decay=weight_decay, name = 'yolo_head_P4')(P4_out)
    out0 = DarknetConv2D_withL2(len(anchors_mask[0]) * (5 + num_classes), (1, 1), strides = (1, 1), weight_decay=weight_decay, name = 'yolo_head_P5')(P5_out)
    return Model(inputs, [out0, out1, out2])

def get_train_model(model_body, input_shape, num_classes, anchors, anchors_mask, label_smoothing, focal_loss, alpha, gamma, iou_type):
    y_true = [Input(shape = (input_shape[0] // {0:32, 1:16, 2:8}[l], input_shape[1] // {0:32, 1:16, 2:8}[l], \
                                len(anchors_mask[l]), num_classes + 5)) for l in range(len(anchors_mask))]
    model_loss  = Lambda(
        yolo_loss, 
        output_shape    = (1, ), 
        name            = 'yolo_loss', 
        arguments       = {
            'input_shape'       : input_shape, 
            'anchors'           : anchors, 
            'anchors_mask'      : anchors_mask, 
            'num_classes'       : num_classes, 
            'balance'           : [0.4, 1.0, 4],
            'box_ratio'         : 0.05,
            'obj_ratio'         : 5 * (input_shape[0] * input_shape[1]) / (416 ** 2), 
            'cls_ratio'         : 1 * (num_classes / 80),
            'label_smoothing'   : label_smoothing,
            'focal_loss'        : focal_loss, 
            'focal_loss_ratio'  : 10,
            'alpha'             : alpha, 
            'gamma'             : gamma,
            'iou_type'          : iou_type,
        }
    )([*model_body.output, *y_true])
    model = Model([model_body.input, *y_true], model_loss)
    return model