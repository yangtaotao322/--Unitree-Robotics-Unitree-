import csv
import math
import os
from datetime import datetime

import rclpy
from gazebo_msgs.msg import ModelStates
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from std_msgs.msg import Bool, String


def clamp(value, lower, upper):
    return max(lower, min(upper, value))


def wrap_angle(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


class PatrolNode(Node):
    def __init__(self):
        super().__init__('lite3_patrol')
        defaults = {
            'model_name': 'robot_model', 'use_dead_reckoning': False,
            'pose_topic': '/ground_truth/odom',
            'relative_waypoints': True,
            'waypoints': [0.0, 0.0, 2.0, 0.0, 2.0, 1.5, 0.0, 0.0],
            'waypoint_names': ['A', 'B', 'C', 'A_return'], 'max_linear_speed': 0.22,
            'min_linear_speed': 0.0,
            'max_angular_speed': 0.55, 'position_tolerance': 0.20, 'heading_tolerance': 0.18,
            'waypoint_timeout': 35.0, 'dwell_seconds': 2.0, 'max_retries': 2,
            'control_rate': 15.0, 'dry_run': False,
            'cmd_vel_topic': '/cmd_vel', 'obstacle_topic': '/patrol/obstacle',
            'status_topic': '/patrol/status',
            'log_directory': '~/lite3_patrol_logs'
        }
        defaults['fall_angle_threshold'] = 0.80
        for key, value in defaults.items():
            self.declare_parameter(key, value)
        self.model_name = self.value('model_name')
        self.use_dead_reckoning = bool(self.value('use_dead_reckoning'))
        flat = list(self.value('waypoints'))
        if len(flat) < 4 or len(flat) % 2:
            raise ValueError('waypoints must contain x,y pairs')
        self.points = [(float(flat[i]), float(flat[i + 1])) for i in range(0, len(flat), 2)]
        self.relative_waypoints = bool(self.value('relative_waypoints'))
        self.origin_applied = False
        self.names = list(self.value('waypoint_names'))
        if len(self.names) != len(self.points):
            self.names = [f'P{i}' for i in range(len(self.points))]
        self.max_v = float(self.value('max_linear_speed'))
        self.min_v = float(self.value('min_linear_speed'))
        self.max_w = float(self.value('max_angular_speed'))
        self.pos_tol = float(self.value('position_tolerance'))
        self.heading_tol = float(self.value('heading_tolerance'))
        self.timeout = float(self.value('waypoint_timeout'))
        self.dwell = float(self.value('dwell_seconds'))
        self.max_retries = int(self.value('max_retries'))
        self.dry_run = bool(self.value('dry_run'))
        self.fall_angle_threshold = float(self.value('fall_angle_threshold'))
        self.pose = (0.0, 0.0, 0.0) if self.use_dead_reckoning else None
        self.last_cmd = (0.0, 0.0)
        self.last_tick = self.now()
        self.index = 0
        self.retry = 0
        self.state = 'GO' if self.use_dead_reckoning else 'WAIT_POSE'
        self.state_since = self.now()
        self.obstacle = False
        self.cmd_pub = self.create_publisher(Twist, str(self.value('cmd_vel_topic')), 10)
        self.status_pub = self.create_publisher(String, str(self.value('status_topic')), 10)
        self.create_subscription(ModelStates, '/gazebo/model_states', self.pose_cb, 10)
        self.create_subscription(Odometry, str(self.value('pose_topic')), self.odom_cb, 10)
        self.create_subscription(Bool, str(self.value('obstacle_topic')), self.obstacle_cb, 10)
        rate = max(2.0, float(self.value('control_rate')))
        self.timer = self.create_timer(1.0 / rate, self.tick)
        log_dir = os.path.expanduser(str(self.value('log_directory')))
        os.makedirs(log_dir, exist_ok=True)
        self.log_path = os.path.join(log_dir, datetime.now().strftime('patrol_%Y%m%d_%H%M%S.csv'))
        with open(self.log_path, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(['time', 'event', 'waypoint', 'x', 'y', 'detail'])
        self.event('START', 'configuration loaded')
        if self.use_dead_reckoning:
            self.event('POSE_READY', 'simulation dead-reckoning enabled')

    def value(self, name):
        return self.get_parameter(name).value

    def now(self):
        return self.get_clock().now().nanoseconds / 1e9

    def pose_cb(self, msg):
        if self.model_name not in msg.name:
            return
        pose = msg.pose[msg.name.index(self.model_name)]
        q = pose.orientation
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y*q.y + q.z*q.z))
        self.pose = (pose.position.x, pose.position.y, yaw)
        if self.state == 'WAIT_POSE':
            self.state = 'GO'
            self.state_since = self.now()
            self.event('POSE_READY', 'starting patrol')

    def odom_cb(self, msg):
        pose = msg.pose.pose
        q = pose.orientation
        sinr = 2.0 * (q.w * q.x + q.y * q.z)
        cosr = 1.0 - 2.0 * (q.x*q.x + q.y*q.y)
        roll = math.atan2(sinr, cosr)
        sinp = clamp(2.0 * (q.w * q.y - q.z * q.x), -1.0, 1.0)
        pitch = math.asin(sinp)
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y*q.y + q.z*q.z))
        self.pose = (pose.position.x, pose.position.y, yaw)
        if self.relative_waypoints and not self.origin_applied:
            self.points = [(pose.position.x + x, pose.position.y + y) for x, y in self.points]
            self.origin_applied = True
        if self.state == 'WAIT_POSE':
            self.state = 'GO'
            self.state_since = self.now()
            self.event('POSE_READY', 'ground-truth odometry received')
        if self.state not in ('WAIT_POSE', 'DONE', 'FAILED') and (
                abs(roll) > self.fall_angle_threshold or abs(pitch) > self.fall_angle_threshold):
            self.state = 'FAILED'
            self.publish_cmd()
            self.event('FAILED', f'fall detected roll={roll:.3f}, pitch={pitch:.3f}')

    def obstacle_cb(self, msg):
        changed = self.obstacle != msg.data
        self.obstacle = msg.data
        if changed:
            self.event('OBSTACLE' if self.obstacle else 'OBSTACLE_CLEARED', '')

    def publish_cmd(self, linear=0.0, angular=0.0):
        msg = Twist()
        if not self.dry_run:
            msg.linear.x = float(linear)
            msg.angular.z = float(angular)
        self.last_cmd = (msg.linear.x, msg.angular.z)
        self.cmd_pub.publish(msg)

    def integrate_pose(self):
        now = self.now()
        dt = clamp(now - self.last_tick, 0.0, 0.2)
        self.last_tick = now
        if not self.use_dead_reckoning or self.pose is None:
            return
        x, y, yaw = self.pose
        linear, angular = self.last_cmd
        yaw = wrap_angle(yaw + angular * dt)
        self.pose = (x + linear * math.cos(yaw) * dt,
                     y + linear * math.sin(yaw) * dt,
                     yaw)

    def event(self, kind, detail):
        name = self.names[self.index] if self.index < len(self.names) else 'DONE'
        x, y = (self.pose[0], self.pose[1]) if self.pose else ('', '')
        text = f'{kind}|{name}|{detail}'
        self.status_pub.publish(String(data=text))
        self.get_logger().info(text)
        with open(self.log_path, 'a', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow([datetime.now().isoformat(timespec='milliseconds'), kind, name, x, y, detail])

    def tick(self):
        self.integrate_pose()
        if self.state in ('WAIT_POSE', 'DONE', 'FAILED'):
            self.publish_cmd()
            return
        if self.obstacle:
            self.publish_cmd()
            return
        elapsed = self.now() - self.state_since
        if self.state == 'DWELL':
            self.publish_cmd()
            if elapsed >= self.dwell:
                self.index += 1
                if self.index >= len(self.points):
                    self.state = 'DONE'
                    self.event('COMPLETE', 'A-B-C-A patrol completed')
                else:
                    self.state = 'GO'
                    self.state_since = self.now()
                    self.event('DEPART', '')
            return
        if elapsed > self.timeout:
            self.publish_cmd()
            self.retry += 1
            if self.retry <= self.max_retries:
                self.state_since = self.now()
                self.event('RETRY', f'{self.retry}/{self.max_retries}')
            else:
                self.state = 'FAILED'
                self.event('FAILED', 'waypoint timeout; robot stopped')
            return
        x, y, yaw = self.pose
        gx, gy = self.points[self.index]
        dx, dy = gx - x, gy - y
        distance = math.hypot(dx, dy)
        if distance <= self.pos_tol:
            self.publish_cmd()
            self.retry = 0
            self.state = 'DWELL'
            self.state_since = self.now()
            self.event('ARRIVED', f'distance={distance:.3f}')
            return
        heading_error = wrap_angle(math.atan2(dy, dx) - yaw)
        angular = clamp(1.6 * heading_error, -self.max_w, self.max_w)
        linear = 0.0 if abs(heading_error) > 0.75 else max(self.min_v, min(self.max_v, 0.7 * distance))
        if abs(heading_error) > self.heading_tol:
            linear *= 0.35
        self.publish_cmd(linear, angular)

    def destroy_node(self):
        if rclpy.ok():
            self.publish_cmd()
            self.event('STOP', 'node shutdown')
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PatrolNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
