import argparse
import io
import logging
import sys
from concurrent import futures

import grpc
import numpy as np
import robodata_pb2
import robodata_pb2_grpc
import torch
from minigpt4_example import Predictor
from PIL import Image

import home_robot.mapping

sys.path.append("../../../../src/home_robot/home_robot/perception/minigpt4/MiniGPT-4")


class RoboDataServicer(robodata_pb2_grpc.RobotDataServicer):
    def __init__(self, args):
        self.obs_history = []
        self._load_llama(args)
        pass

    def _load_llama(self, args):
        self.predictor = Predictor(args)

    def _robotensor_to_tensor(self, proto_tensor):
        tensor = torch.load(io.BytesIO(proto_tensor.tensor_content))
        return tensor

    def GetHistory(self, request, context):
        """Return the first RobotSummary object in history."""
        yield self.obs_history.pop(0)

    def PlanHighLevelAction(self, request, context):
        """Return text string (action) when given a stream of RobotSummary objects.
        Each RobotSummary has object crops stored within the instance_image field, and at least one RobotSummary should
        have the prompt contained in the message field."""
        req_msg = ""
        obj_crops = []
        for r in request:
            req_msg = req_msg + r.message
            for im in r.instance_image:
                tensor_img = self._robotensor_to_tensor(im)
                print(tensor_img.shape)
                post_img = self.predictor.vis_processor(
                    Image.fromarray(np.array(tensor_img).astype(np.uint8))
                )
                print(post_img.shape)
                obj_crops.append(post_img)
        chat_input = {
            "prompt": [req_msg],
            "crops": torch.stack(obj_crops, dim=0).unsqueeze(0),
            "images": [],
        }
        print("len of crops:" + str(len(obj_crops)))
        with torch.no_grad():
            response = self.predictor.model._generate_answers(
                chat_input,
                num_beams=1,  # self.predictor.num_beams,
                max_length=self.predictor.max_len,
                min_length=self.predictor.min_len,
            )
            print(response)
        x = robodata_pb2.RobotSummary()
        x.message = str(response[0])
        yield x

    def ReceiveRobotData(self, request, context):
        print("entered ReceiveRobotData")
        for r in request:
            self.obs_history.append(r)
        x = robodata_pb2.RobotSummary()
        x.message = "Robot data received"
        yield x

    def Chat(self, request, context):
        print("Entered Chat")
        prompt = "Task: You are a chatbot exploring a home."
        # TODO something more sophisticated
        prompt = prompt + request.conversation[-1].content
        print("prompt: " + str(prompt))
        imgs = []
        crop_text = ""
        for r in request.imgs:
            imgs.append(self._robotensor_to_tensor(r))
            crop_text += f"<crop_{r.id}><crophere_{r.id}></crop_{r.id}>,"
            crop_text = crop_text[:-1] + ". "

        chat_input = {
            "prompt": [crop_text + prompt],
            "crops": [],
            "images": torch.stack(imgs, dim=0).unsqueeze(0),
        }
        with torch.no_grad():
            response = self.predictor.model._generate_answers(
                chat_input,
                num_beams=1,  # self.predictor.num_beams,
                max_length=self.predictor.max_len,
                min_length=self.predictor.min_len,
            )
            print(response)
        x = robodata_pb2.ChatMsg()
        x.role = "VLM"
        x.content = str(response[0])
        yield x


def serve(args=None):
    maxMsgLength = 1024 * 1024 * 8
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=10),
        options=[
            ("grpc.max_message_length", maxMsgLength),
            ("grpc.max_send_message_length", maxMsgLength),
            ("grpc.max_receive_message_length", maxMsgLength),
        ],
    )
    robodata_pb2_grpc.add_RobotDataServicer_to_server(RoboDataServicer(args), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    print("started RoboData server")
    server.wait_for_termination()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="")
    parser.add_argument(
        "--enable_vlm",
        default=0,
        type=int,
        help="Enable loading Minigpt4",
    )
    parser.add_argument(
        "--task",
        default="find a green bottle",
        help="Specify any task in natural language for VLM",
    )
    parser.add_argument(
        "--cfg-path",
        default="./proto_robot/ovmm_test.yaml",
        # default="../../../src/home_robot/home_robot/perception/minigpt4/MiniGPT-4/eval_configs/ovmm_test.yaml",
        help="path to configuration file.",
    )
    parser.add_argument(
        "--gpu-id", type=int, default=0, help="specify the gpu to load the model."
    )
    parser.add_argument(
        "--planning_times",
        default=1,
        help="Num of times of calling VLM for inference -- might be useful for long context length",
    )
    parser.add_argument(
        "--context_length",
        default=20,
        help="Maximum number of images the vlm can reason about",
    )

    parser.add_argument(
        "--options",
        nargs="+",
        help="For minigpt4 configs: override some settings in the used config, the key-value pair "
        "in xxx=yyy format will be merged into config file (deprecate), "
        "change to --cfg-options instead.",
    )
    args = parser.parse_args()

    logging.basicConfig()
    serve(args=args)
