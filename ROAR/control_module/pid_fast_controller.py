from operator import truediv
from matplotlib.pyplot import close
from pydantic import BaseModel, Field
from ROAR.control_module.controller import Controller
from ROAR.utilities_module.vehicle_models import VehicleControl, Vehicle
# import keyboard

from ROAR.utilities_module.data_structures_models import Transform, Location, Rotation
from collections import deque
import numpy as np
import math
import logging
from ROAR.agent_module.agent import Agent
from typing import Tuple
import json
from pathlib import Path
from ROAR.planning_module.mission_planner.waypoint_following_mission_planner import WaypointFollowingMissionPlanner

class PIDFastController(Controller):
    def __init__(self, agent, steering_boundary: Tuple[float, float],
                 throttle_boundary: Tuple[float, float], **kwargs):
        super().__init__(agent, **kwargs)
        self.max_speed = self.agent.agent_settings.max_speed
        throttle_boundary = throttle_boundary
        self.steering_boundary = steering_boundary
        self.config = json.load(Path(agent.agent_settings.pid_config_file_path).open(mode='r'))
        
        # useful variables
        self.region = 1
        self.brake_counter = 0

        self.waypoint_queue_region = []
        with open("ROAR\\control_module\\region_list.txt") as f:
            for line in f:
                raw = line.split(",")
                waypoint = Transform(location=Location(x=raw[0], y=raw[1], z=raw[2]), rotation=Rotation(pitch=0, yaw=0, roll=0))
                self.waypoint_queue_region.append(waypoint)

        self.waypoint_queue_braking = []
        with open("ROAR\\control_module\\braking_list_mod.txt") as f:
            for line in f:
                raw = line.split(",")
                waypoint = Transform(location=Location(x=raw[0], y=raw[1], z=raw[2]), rotation=Rotation(pitch=0, yaw=0, roll=0))
                self.waypoint_queue_braking.append(waypoint)

        self.lat_pid_controller = LatPIDController(
            agent=agent,
            config=self.config["latitudinal_controller"],
            steering_boundary=steering_boundary
        )
        self.logger = logging.getLogger(__name__)

    def run_in_series(self, next_waypoint: Transform, close_waypoint: Transform, far_waypoint: Transform, **kwargs) -> VehicleControl:

        # run lat pid controller
        steering, error, wide_error, sharp_error = self.lat_pid_controller.run_in_series(next_waypoint=next_waypoint, close_waypoint=close_waypoint, far_waypoint=far_waypoint)
        
        
        current_speed = Vehicle.get_speed(self.agent.vehicle)

        # get errors from lat pid
        error = abs(round(error, 3))
        wide_error = abs(round(wide_error, 3))
        sharp_error = abs(round(sharp_error, 3))
        #print(error, wide_error, sharp_error)

        # calculate change in pitch
        pitch = float(next_waypoint.record().split(",")[4])

        waypoint = self.waypoint_queue_braking[0]
        dist = self.agent.vehicle.transform.location.distance(waypoint.location)

        print("Region = {}, Distance = {}, Steering = {}, Speed = {}, Error = {}, Wide Error = {}, Sharp Error = {}".format(self.region, dist, steering, current_speed, error, wide_error, sharp_error))


        if self.region == 1:
            if sharp_error < 0.68 or current_speed <= 105:
                throttle = 1
                brake = 0
            else:
                throttle = -0.55
                brake = 1

        elif self.region == 2:
            if sharp_error >= 0.68 and current_speed > 80:
                throttle = -0.6
                brake = 1
            elif wide_error > 0.09 and current_speed > 92: # wide turn
                throttle = max(0, 1 - 6*pow(wide_error + current_speed*0.003, 6))
                brake = 0
            else:
                throttle = 1
                brake = 0

        #Downtown 1 - Starting Downtown
        elif self.region == 3:
            if sharp_error < 0.67 or current_speed <= 105:
                throttle = 1
                brake = 0
            else:
                throttle = -0.555
                brake = 0.87
            if sharp_error >= 0.67 and current_speed > 105:
                throttle = -0.0555
                brake = 0.87
            elif wide_error > 0.09 and current_speed > 185: # wide turn
                throttle = max(0, 1 - 3*pow(wide_error + current_speed*0.003, 6))
                brake = 0
            else:
                throttle = 1
                brake = 0           

        #Hill Region 3 - Start of hills/Continuation of hills
        elif self.region == 4:
            waypoint = self.waypoint_queue_braking[0] # 5012 is weird bump spot
            dist = self.agent.vehicle.transform.location.distance(waypoint.location)
            if dist <= 5:
                self.brake_counter = 1
                # print(self.waypoint_queue_braking[0])
                self.waypoint_queue_braking.pop(0)
            if self.brake_counter > 0:
                throttle = -1
                brake = 1
                self.brake_counter += 1
                if self.brake_counter >= 4:
                    self.brake_counter = 0
            elif sharp_error >= 0.67 and current_speed > 80:
                throttle = 0
                brake = 0.4
            elif wide_error > 0.09 and current_speed > 92: # wide turn
                throttle = max(0, 1 - 6*pow(wide_error + current_speed*0.003, 6))
                brake = 0
            else:
                throttle = 1
                brake = 0

        #Hybrid 1 - Straight patch in hills
        elif self.region == 5:
            if sharp_error < 0.67 or current_speed <= 100:
                throttle = 1
                brake = 0
            elif sharp_error >= 0.66 and current_speed > 83:
                throttle = -0.4
                brake = 0.9
            elif wide_error > 0.09 and current_speed > 92: # wide turn
                throttle = max(0, 1 - 6*pow(wide_error + current_speed*0.003, 6))
                brake = 0
            if current_speed >= 220:
                throttle = -0.4
                brake = 1

        #Turn 1 - Hills after first major straight patch
        elif self.region == 6:
            steering = 0.3875
            # Steering goes between -1 and 1, -1 means left and 1 means right
            if sharp_error >= 0.66 and current_speed > 83:
                steering = 0.03
                throttle = 0
                brake = 1
            elif wide_error > 0.09 and current_speed > 92: # wide turn
                steering = 0.03
                throttle = max(0, 1 - 6*pow(wide_error + current_speed*0.003, 6))
                brake = 0
            else:
                steering = 0.03
                throttle = 1
                brake = 0

        #Hybrid 2 - Second straight patch in hills
        elif self.region == 7:
            if sharp_error < 0.67 or current_speed <= 100:
                throttle = 1
                brake = 0
            elif sharp_error >= 0.66 and current_speed > 83:
                throttle = -0.4
                brake = 0.9
            elif wide_error > 0.09 and current_speed > 92: # wide turn
                throttle = max(0, 1 - 6*pow(wide_error + current_speed*0.003, 6))
                brake = 0
            if current_speed >= 220:
                throttle = -0.4
                brake = 1

        #Turn 2 - Hills after second major straight patch
        elif self.region == 8:
            steering = 0.375
            if sharp_error >= 0.66 and current_speed > 83:
                steering = 0.03
                throttle = 0
                brake = 1
            elif wide_error > 0.09 and current_speed > 92: # wide turn
                steering = 0.03
                throttle = max(0, 1 - 6*pow(wide_error + current_speed*0.003, 6))
                brake = 0
            else:
                steering = 0.03
                throttle = 1
                brake = 0
        
        #Hybrid 3 - Third straight patch in hills
        elif self.region == 9:
            if sharp_error < 0.67 or current_speed <= 100:
                throttle = 1
                brake = 0
            elif sharp_error >= 0.66 and current_speed > 83:
                throttle = -0.4
                brake = 0.9
            elif wide_error > 0.09 and current_speed > 92: # wide turn
                throttle = max(0, 1 - 6*pow(wide_error + current_speed*0.003, 6))
                brake = 0
            if current_speed >= 220:
                throttle = -0.4
                brake = 1

        #Turn 3 - Hills after third major straight patch
        elif self.region == 10:
            waypoint = self.waypoint_queue_braking[0] # 5012 is weird bump spot
            dist = self.agent.vehicle.transform.location.distance(waypoint.location)
            if dist <= 5:
                self.brake_counter = 1
                # print(self.waypoint_queue_braking[0])
                self.waypoint_queue_braking.pop(0)
            if self.brake_counter > 0:
                throttle = -1
                brake = 1
                self.brake_counter += 1
                if self.brake_counter >= 4:
                    self.brake_counter = 0
            if current_speed >= 200:
                throttle = -0.4
                brake = 1
            elif sharp_error >= 0.67 and current_speed > 80:
                throttle = 0
                brake = 0.4
            elif wide_error > 0.09 and current_speed > 92: # wide turn
                throttle = max(0, 1 - 6*pow(wide_error + current_speed*0.003, 6))
                brake = 0
            else:
                throttle = 1
                brake = 0

        #Downtown 4 - End of hills re-entering downtown
        elif self.region == 11:
            if sharp_error < 0.74 or current_speed <= 89:
                throttle = 1
                brake = 0
                if current_speed >= 158:
                    brake = 1
            else:
                throttle = -1
                brake = 1

        #Hill Region 4 - 2nd bump turn
        elif self.region == 12:
            waypoint = self.waypoint_queue_braking[0] # 5012 is weird bump spot
            dist = self.agent.vehicle.transform.location.distance(waypoint.location)
            if dist <= 5:
                self.brake_counter = 1
                # print(self.waypoint_queue_braking[0])
                self.waypoint_queue_braking.pop(0)
            if self.brake_counter > 0:
                throttle = -1
                brake = 1
                self.brake_counter += 1
                if self.brake_counter >= 4:
                    self.brake_counter = 0
            elif sharp_error >= 0.68 and current_speed > 84:
                throttle = 0.45
                brake = 0.5
            elif wide_error > 0.09 and current_speed > 92: # wide turn
                throttle = max(0, 1 - 6*pow(wide_error + current_speed*0.003, 6))
                brake = 0
            else:
                throttle = 1
                brake = 0
                
        #Downtown 5 - After 2nd bump turn
        elif self.region == 13:
            if sharp_error < 0.74 or current_speed <= 90:
                throttle = 1
                brake = 0
                if current_speed >= 165:
                    throttle = -0.3
                    brake = 1
            else:
                throttle = -1
                brake = 1

        #Hill Region 5 - 3rd bump turn
        elif self.region == 14:
            if sharp_error >= 0.68 and current_speed > 80:
                throttle = -0.6
                brake = 1
            elif wide_error > 0.09 and current_speed > 92: # wide turn
                throttle = max(0, 1 - 6*pow(wide_error + current_speed*0.003, 6))
                brake = 0
            else:
                throttle = 1
                brake = 0

        #Hills Region 6 - Smooth turns before roundabout
        elif self.region == 15:
            waypoint = self.waypoint_queue_braking[0] # 5012 is weird bump spot
            dist = self.agent.vehicle.transform.location.distance(waypoint.location)
            if dist <= 3.5:
                self.brake_counter = 1
                # print(self.waypoint_queue_braking[0])
                self.waypoint_queue_braking.pop(0)
            if self.brake_counter > 0:
                throttle = -1
                brake = 1
                self.brake_counter += 1
                if self.brake_counter >= 4:
                    self.brake_counter = 0
            elif sharp_error >= 0.66 and current_speed > 86:
                throttle = 0.95
                brake = 0
            elif wide_error > 0.09 and current_speed > 92: # wide turn
                throttle = max(0, 1 - 6*pow(wide_error + current_speed*0.003, 6))
                brake = 0
            else:
                throttle = 1
                brake = 0

        #Hill Region 8 - Roundabout
        elif self.region == 16:
            waypoint = self.waypoint_queue_braking[0] # 5012 is weird bump spot
            dist = self.agent.vehicle.transform.location.distance(waypoint.location)
            if dist <= 6:
                self.brake_counter = 1
                # print(self.waypoint_queue_braking[0])
                self.waypoint_queue_braking.pop(0)
            if self.brake_counter > 0:
                throttle = -1
                brake = 1
                self.brake_counter += 1
                if self.brake_counter >= 4:
                    self.brake_counter = 0
            if current_speed > 106:
                throttle = -0.2
                brake = 1
            elif sharp_error >= 0.64 and current_speed > 80:
                throttle = -0.4
                brake = 0.9
            elif wide_error > 0.09 and current_speed > 92: # wide turn
                throttle = max(0, 1 - 6*pow(wide_error + current_speed*0.003, 6))
                brake = 0
            else:
                throttle = 1
                brake = 0        

        # Hill Region 9 - End straightaway
        elif self.region == 17:
            if current_speed >= 120:
                throttle = 0.3
                brake = 1
            elif sharp_error >= 0.67 and current_speed > 80:
                throttle = 0
                brake = 0.4
            elif wide_error > 0.09 and current_speed > 92: # wide turn
                throttle = max(0, 1 - 6*pow(wide_error + current_speed*0.003, 6))
                brake = 0
            else:
                throttle = 1
                brake = 0

        gear = max(1, (int)((current_speed - 2 * pitch) / 60))
        if throttle == -1:
            gear = -1
        
        waypoint = self.waypoint_queue_region[0]
        dist = self.agent.vehicle.transform.location.distance(waypoint.location)
        if dist <= 10:
            self.region += 1
            self.waypoint_queue_region.pop(0)
        
        # if keyboard.is_pressed("space"):
        #      print(self.agent.vehicle.transform.record())
        
        return VehicleControl(throttle=throttle, steering=steering, brake=brake, gear=gear)

    @staticmethod
    def find_k_values(vehicle: Vehicle, config: dict) -> np.array:
        current_speed = Vehicle.get_speed(vehicle=vehicle)
        k_p, k_d, k_i = 1, 0, 0
        for speed_upper_bound, kvalues in config.items():
            speed_upper_bound = float(speed_upper_bound)
            if current_speed < speed_upper_bound:
                k_p, k_d, k_i = kvalues["Kp"], kvalues["Kd"], kvalues["Ki"]
                break
        return np.array([k_p, k_d, k_i])

class LatPIDController(Controller):
    def __init__(self, agent, config: dict, steering_boundary: Tuple[float, float],
                 dt: float = 0.03, **kwargs):
        super().__init__(agent, **kwargs)
        self.config = config
        self.steering_boundary = steering_boundary
        self._error_buffer = deque(maxlen=10)
        self._dt = dt

    def run_in_series(self, next_waypoint: Transform, close_waypoint: Transform, far_waypoint: Transform, **kwargs) -> float:
        """
        Calculates a vector that represent where you are going.
        Args:
            next_waypoint ():
            **kwargs ():

        Returns:
            lat_control
        """
        # calculate a vector that represent where you are going
        v_begin = self.agent.vehicle.transform.location.to_array()
        direction_vector = np.array([-np.sin(np.deg2rad(self.agent.vehicle.transform.rotation.yaw)),
                                     0,
                                     -np.cos(np.deg2rad(self.agent.vehicle.transform.rotation.yaw))])
        v_end = v_begin + direction_vector

        v_vec = np.array([(v_end[0] - v_begin[0]), 0, (v_end[2] - v_begin[2])])
        
        # calculate error projection
        w_vec = np.array(
            [
                next_waypoint.location.x - v_begin[0],
                0,
                next_waypoint.location.z - v_begin[2],
            ]
        )

        v_vec_normed = v_vec / np.linalg.norm(v_vec)
        w_vec_normed = w_vec / np.linalg.norm(w_vec)
        #error = np.arccos(v_vec_normed @ w_vec_normed.T)
        error = np.arccos(min(max(v_vec_normed @ w_vec_normed.T, -1), 1)) # makes sure arccos input is between -1 and 1, inclusive
        _cross = np.cross(v_vec_normed, w_vec_normed)

        # calculate close error projection
        w_vec = np.array(
            [
                close_waypoint.location.x - v_begin[0],
                0,
                close_waypoint.location.z - v_begin[2],
            ]
        )
        w_vec_normed = w_vec / np.linalg.norm(w_vec)
        #wide_error = np.arccos(v_vec_normed @ w_vec_normed.T)
        wide_error = np.arccos(min(max(v_vec_normed @ w_vec_normed.T, -1), 1)) # makes sure arccos input is between -1 and 1, inclusive

        # calculate far error projection
        w_vec = np.array(
            [
                far_waypoint.location.x - v_begin[0],
                0,
                far_waypoint.location.z - v_begin[2],
            ]
        )
        w_vec_normed = w_vec / np.linalg.norm(w_vec)
        #sharp_error = np.arccos(v_vec_normed @ w_vec_normed.T)
        sharp_error = np.arccos(min(max(v_vec_normed @ w_vec_normed.T, -1), 1)) # makes sure arccos input is between -1 and 1, inclusive

        if _cross[1] > 0:
            error *= -1
        self._error_buffer.append(error)
        if len(self._error_buffer) >= 2:
            _de = (self._error_buffer[-1] - self._error_buffer[-2]) / self._dt
            _ie = sum(self._error_buffer) * self._dt
        else:
            _de = 0.0
            _ie = 0.0

        k_p, k_d, k_i = PIDFastController.find_k_values(config=self.config, vehicle=self.agent.vehicle)

        lat_control = float(
            np.clip((k_p * error) + (k_d * _de) + (k_i * _ie), self.steering_boundary[0], self.steering_boundary[1])
        )
        return lat_control, error, wide_error, sharp_error
