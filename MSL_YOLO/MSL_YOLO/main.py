import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np

import torch
import torch.backends.cudnn as cudnn

from MSL_YOLO.models.common import DetectMultiBackend
from MSL_YOLO.utils.datasets import IMG_FORMATS, VID_FORMATS
from MSL_YOLO.utils.general import (LOGGER, check_img_size, check_imshow, non_max_suppression, scale_coords, xyxy2xywh)
from MSL_YOLO.utils.plots import Annotator, colors
from MSL_YOLO.utils.torch_utils import select_device, time_sync

from MSL_YOLO.utils.datasets import letterbox

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from bboxes_ex_msgs.msg import BoundingBoxes, BoundingBox
from std_msgs.msg import Header, Float32, Float32MultiArray
from cv_bridge import CvBridge


class yolov5_demo():
    def __init__(self,  weights,
                        data,
                        imagez_height,
                        imagez_width,
                        conf_thres,
                        iou_thres,
                        max_det,
                        device,
                        view_img,
                        classes,
                        agnostic_nms,
                        line_thickness,
                        half,
                        dnn
                        ):
        self.weights = weights
        self.data = data
        self.imagez_height = imagez_height
        self.imagez_width = imagez_width
        self.conf_thres = conf_thres
        self.iou_thres = iou_thres
        self.max_det = max_det
        self.device = device
        self.view_img = view_img
        self.classes = classes
        self.agnostic_nms = agnostic_nms
        self.line_thickness = line_thickness
        self.half = half
        self.dnn = dnn

        self.s = str()

        self.load_model()

    def load_model(self):
        imgsz = (self.imagez_height, self.imagez_width)

        # Load model
        self.device = select_device(self.device)
        self.model = DetectMultiBackend(self.weights, device=self.device, dnn=self.dnn, data=self.data)
        stride, self.names, pt, jit, onnx, engine = self.model.stride, self.model.names, self.model.pt, self.model.jit, self.model.onnx, self.model.engine
        imgsz = check_img_size(imgsz, s=stride)  # check image size

        # Half
        self.half &= (pt or jit or onnx or engine) and self.device.type != 'cpu'  # FP16 supported on limited backends with CUDA
        if pt or jit:
            self.model.model.half() if self.half else self.model.model.float()

        source = 0
        # Dataloader
        webcam = True
        if webcam:
            view_img = check_imshow()
            cudnn.benchmark = True
        bs = 1
        self.vid_path, self.vid_writer = [None] * bs, [None] * bs

        self.model.warmup(imgsz=(1 if pt else bs, 3, *imgsz))  # warmup
        self.dt, self.seen = [0.0, 0.0, 0.0], 0

    # callback ==========================================================================

    # return ---------------------------------------
    # 1. class (str)                                +
    # 2. confidence (float)                         +
    # 3. x_min, y_min, x_max, y_max (float)         +
    # ----------------------------------------------
    def image_callback(self, image_raw):
        class_list = []
        confidence_list = []
        x_min_list = []
        y_min_list = []
        x_max_list = []
        y_max_list = []

        # im is  NDArray[_SCT@ascontiguousarray
        # im = im.transpose(2, 0, 1)
        self.stride = 32  # stride
        self.img_size = 640
        img = letterbox(image_raw, self.img_size, stride=self.stride)[0]

        # Convert
        img = img.transpose((2, 0, 1))[::-1]  # HWC to CHW, BGR to RGB
        im = np.ascontiguousarray(img)

        t1 = time_sync()
        im = torch.from_numpy(im).to(self.device)
        im = im.half() if self.half else im.float()  # uint8 to fp16/32
        im /= 255  # 0 - 255 to 0.0 - 1.0
        if len(im.shape) == 3:
            im = im[None]  # expand for batch dim
        t2 = time_sync()
        self.dt[0] += t2 - t1

        # Inference
        save_dir = "runs/detect/exp7"
        path = ['0']

        # visualize = increment_path(save_dir / Path(path).stem, mkdir=True) if visualize else False
        pred = self.model(im, augment=False, visualize=False)
        t3 = time_sync()
        self.dt[1] += t3 - t2

        # NMS
        pred = non_max_suppression(pred, self.conf_thres, self.iou_thres, self.classes, self.agnostic_nms, max_det=self.max_det)
        self.dt[2] += time_sync() - t3

        # Process predictions
        for i, det in enumerate(pred):
            im0 = image_raw
            self.s += f'{i}: '

            # p = Path(str(p))  # to Path
            self.s += '%gx%g ' % im.shape[2:]  # print string
            gn = torch.tensor(im0.shape)[[1, 0, 1, 0]]  # normalization gain whwh
            # imc = im0.copy() if save_crop else im0  # for save_crop
            annotator = Annotator(im0, line_width=self.line_thickness, example=str(self.names))
            if len(det):
                # Rescale boxes from img_size to im0 size
                det[:, :4] = scale_coords(im.shape[2:], det[:, :4], im0.shape).round()

                # Print results
                for c in det[:, -1].unique():
                    n = (det[:, -1] == c).sum()  # detections per class
                    self.s += f"{n} {self.names[int(c)]}{'s' * (n > 1)}, "  # add to string

                for *xyxy, conf, cls in reversed(det):
                    xywh = (xyxy2xywh(torch.tensor(xyxy).view(1, 4)) / gn).view(-1).tolist()  # normalized xywh
                    save_conf = False
                    line = (cls, *xywh, conf) if save_conf else (cls, *xywh)  # label format
                    
                    # Add bbox to image
                    c = int(cls)  # integer class
                    label = f'{self.names[c]} {conf:.2f}'
                    annotator.box_label(xyxy, label, color=colors(c, True))

                    # print(xyxy, label)
                    class_list.append(self.names[c])
                    confidence_list.append(conf)
                    # tensor to float
                    x_min_list.append(xyxy[0].item())
                    y_min_list.append(xyxy[1].item())
                    x_max_list.append(xyxy[2].item())
                    y_max_list.append(xyxy[3].item())

            # Stream results
            im0 = annotator.result()
            if self.view_img:
                cv2.imshow("yolov5", im0)
                cv2.waitKey(1)  # 1 millisecond

            return class_list, confidence_list, x_min_list, y_min_list, x_max_list, y_max_list

class MSL_YOLO(Node):
    def __init__(self):
        super().__init__('MSL_YOLO')

        self.bridge = CvBridge()

        self.pub_bbox = self.create_publisher(BoundingBoxes, 'yolov5/bounding_boxes', 10)
        self.pub_image = self.create_publisher(Image, 'yolov5/image_raw', 10)
        self.pub_depths = self.create_publisher(Float32, 'yolov5/detected_object_depths', 10)

        # self.sub_image = self.create_subscription(Image, 'color/image', self.image_callback, 10)
        # self.depth_image = self.create_subscription(Image, 'stereo/converted_depth', self.depth_callback, 10)

        self.sub_image = self.create_subscription(Image, 'color/video/image', self.image_callback, 10)
        self.depth_image = self.create_subscription(Image, 'stereo/depth', self.depth_callback, 10)

        # parameter
        FILE = Path(__file__).resolve()
        ROOT = FILE.parents[0]
        if str(ROOT) not in sys.path:
            sys.path.append(str(ROOT))  # add ROOT to PATH
        ROOT = Path(os.path.relpath(ROOT, Path.cwd()))

        self.declare_parameter('weights', str(ROOT) + '/config/yolov5s.pt')
        self.declare_parameter('data', str(ROOT) + '/data/coco128.yaml')
        self.declare_parameter('imagez_height', 640)
        self.declare_parameter('imagez_width', 640)
        self.declare_parameter('conf_thres', 0.25)
        self.declare_parameter('iou_thres', 0.45)
        self.declare_parameter('max_det', 1000)
        self.declare_parameter('device', 'cpu')
        self.declare_parameter('view_img', True)
        self.declare_parameter('classes', None)
        self.declare_parameter('agnostic_nms', False)
        self.declare_parameter('line_thickness', 2)
        self.declare_parameter('half', False)
        self.declare_parameter('dnn', False)

        self.weights = self.get_parameter('weights').value
        self.data = self.get_parameter('data').value
        self.imagez_height = self.get_parameter('imagez_height').value
        self.imagez_width = self.get_parameter('imagez_width').value
        self.conf_thres = self.get_parameter('conf_thres').value
        self.iou_thres = self.get_parameter('iou_thres').value
        self.max_det = self.get_parameter('max_det').value
        self.device = self.get_parameter('device').value
        self.view_img = self.get_parameter('view_img').value
        self.classes = self.get_parameter('classes').value
        self.agnostic_nms = self.get_parameter('agnostic_nms').value
        self.line_thickness = self.get_parameter('line_thickness').value
        self.half = self.get_parameter('half').value
        self.dnn = self.get_parameter('dnn').value

        self.yolov5 = yolov5_demo(self.weights,
                                self.data,
                                self.imagez_height,
                                self.imagez_width,
                                self.conf_thres,
                                self.iou_thres,
                                self.max_det,
                                self.device,
                                self.view_img,
                                self.classes,
                                self.agnostic_nms,
                                self.line_thickness,
                                self.half,
                                self.dnn)
        self.x_min_list = [] 
        self.y_min_list = []
        self.x_max_list = []
        self.y_max_list = []
    
    def yolovFive2bboxes_msgs(self, bboxes:list, scores:list, cls:list, img_header:Header):
        bboxes_msg = BoundingBoxes()
        bboxes_msg.header = img_header
        print(bboxes)
        # print(bbox[0][0])
        i = 0
        for score in scores:
            one_box = BoundingBox()
            one_box.xmin = int(bboxes[0][i])
            one_box.ymin = int(bboxes[1][i])
            one_box.xmax = int(bboxes[2][i])
            one_box.ymax = int(bboxes[3][i])
            one_box.probability = float(score)
            one_box.class_id = cls[i]
            bboxes_msg.bounding_boxes.append(one_box)
            i = i+1
        
        return bboxes_msg


    def image_callback(self, image:Image):
        image_raw = self.bridge.imgmsg_to_cv2(image, "bgr8")
        # return (class_list, confidence_list, x_min_list, y_min_list, x_max_list, y_max_list)
        class_list, confidence_list, self.x_min_list, self.y_min_list, self.x_max_list, self.y_max_list = self.yolov5.image_callback(image_raw)

        msg = self.yolovFive2bboxes_msgs(bboxes=[self.x_min_list, self.y_min_list, self.x_max_list, self.y_max_list], scores=confidence_list, cls=class_list, img_header=image.header)
        self.pub_bbox.publish(msg)

        self.pub_image.publish(image)

        print("start ==================")
        print(class_list, confidence_list, self.x_min_list, self.y_min_list, self.x_max_list, self.y_max_list)
        print("end ====================")
    
    def depth_callback(self, image:Image):
        # When we get a depth map, run this. If we don't currently have any objects detected, this gets skipped. 

        depth_raw = self.bridge.imgmsg_to_cv2(image, "32FC1") # Convert the Image message into a cv2 array

        # Iterate over each detected object
        if len(self.x_min_list) > 0: # Arbitrary. Could've picked self.y_min_list, self.x_max_list, self.y_max_list
            centers = [((self.x_min_list[idx] + self.x_max_list[idx])/2, (self.y_min_list[idx] + self.y_max_list[idx])/2) for idx in range(len(self.x_min_list))] # Pick the center pixel of each detected object
            depths = []
            for center in centers:
                depths.append(max(depth_raw))
            # self.pub_depths(depths)
            # msg = Float32MultiArray()
            msg = Float32()
            msg.data = 1.0
            self.pub_depths.publish(msg)

        # for center in centers:

        #     pass

        else:
            msg = Float32()
            msg.data = 2.0
            self.pub_depths.publish(msg)



def ros_main(args=None):
    rclpy.init(args=args)
    yolov5_node = MSL_YOLO()
    rclpy.spin(yolov5_node)
    yolov5_node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    ros_main()