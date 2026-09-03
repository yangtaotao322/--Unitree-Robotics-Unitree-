# Lite3 A-B-C-A 巡检控制器

一个面向云深处 Lite3 的 ROS 2 巡检示例。节点读取机器人位姿、发布
`geometry_msgs/Twist`，依次到达 A、B、C 并返回 A，同时提供到点判断、超时重试、
障碍停车、翻倒保护、状态发布和 CSV 日志。

> 本仓库是独立的巡检控制层，不包含 Lite3 官方 SDK、模型、强化学习控制器或 Gazebo
> 资源。使用者需自行获取并遵守对应软件许可。

## 已验证环境

- Ubuntu 22.04
- ROS 2 Humble
- Gazebo Classic 11
- Lite3 仿真控制器（订阅 `/cmd_vel`）
- 平坦 `earth.world` 场景

## 路线与实测结果

默认仿真路线使用相对坐标：

```text
A(0.0, 0.0) -> B(2.0, 0.0) -> C(2.0, 1.5) -> A(0.0, 0.0)
```

总长度约 6 m。2026-09-03 的两轮平地测试约 80–81 s 完成，各点到达误差约
0.145–0.150 m，无重试、无翻倒。

## 仓库结构

```text
lite3_patrol/
├── config/
│   ├── sim.yaml
│   └── real_low_speed.yaml
├── docs/LITE3_INTEGRATION.md
├── integration/gazebo_ground_truth_plugin.xml
├── launch/patrol.launch.py
├── lite3_patrol/patrol_node.py
├── package.xml
└── setup.py
```

## 安装与编译

```bash
mkdir -p ~/rl_sar/src
cd ~/rl_sar/src
git clone https://github.com/YOUR_NAME/lite3_patrol.git
cd ..
source /opt/ros/humble/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --packages-select lite3_patrol --symlink-install
source install/setup.bash
```

## 仿真准备

1. 按 Lite3 项目原有流程启动 Gazebo 和运动控制器。
2. 确保仿真发布 `/ground_truth/odom`，接入方法见
   [`docs/LITE3_INTEGRATION.md`](docs/LITE3_INTEGRATION.md)。
3. 让机器人起身、进入行走状态并开启 Navigation 模式。
4. 检查接口：

```bash
ros2 topic echo /ground_truth/odom --once
ros2 topic info /cmd_vel
```

## 运行

```bash
source /opt/ros/humble/setup.bash
source ~/rl_sar/install/setup.bash
ros2 launch lite3_patrol patrol.launch.py
```

指定配置文件：

```bash
ros2 launch lite3_patrol patrol.launch.py \
  config:=$HOME/rl_sar/src/lite3_patrol/config/sim.yaml
```

查看状态与日志：

```bash
ros2 topic echo /patrol/status
ls -lt ~/lite3_patrol_logs
```

状态事件包括 `START`、`POSE_READY`、`DEPART`、`ARRIVED`、`RETRY`、
`OBSTACLE`、`FAILED` 和 `COMPLETE`。

## 障碍停车接口

```bash
ros2 topic pub --once /patrol/obstacle std_msgs/msg/Bool '{data: true}'
ros2 topic pub --once /patrol/obstacle std_msgs/msg/Bool '{data: false}'
```

收到 `true` 后持续发布零速度；收到 `false` 后继续当前目标。

## 主要参数

| 参数 | 含义 |
|---|---|
| `pose_topic` | 位姿里程计话题 |
| `relative_waypoints` | 路点是否相对启动位置 |
| `waypoints` | 展平后的 `[x1,y1,x2,y2,...]` |
| `max_linear_speed` | 最大线速度 |
| `min_linear_speed` | 克服控制器死区的最低有效速度 |
| `max_angular_speed` | 最大角速度 |
| `position_tolerance` | 到点距离阈值 |
| `waypoint_timeout` | 单个目标超时时间 |
| `max_retries` | 超时重试次数 |
| `fall_angle_threshold` | roll/pitch 翻倒阈值，单位 rad |
| `dry_run` | 为 `true` 时始终输出零速度 |

## 低速实机验证

`real_low_speed.yaml` 默认 `dry_run: true`，不会驱动机器狗。实机测试前：

1. 确认 `/odom` 是可靠定位数据。
2. 清空场地并安排一人随时操作急停。
3. 保持 `dry_run: true` 检查位姿、状态和路线。
4. 缩短路线，先测试单点和 A→B→A。
5. 人工确认安全后才把 `dry_run` 改为 `false`。
6. 验证通过后再逐级增加距离和速度。

仿真成功不代表实机安全。摩擦、定位漂移、通信延迟、地形及控制器响应均与仿真不同，
必须保留厂家急停方式和现场监护。

## 控制逻辑

节点采用“转向目标 + 距离比例速度”控制。航向误差较大时停止或降低直行速度，接近目标
时降速；最低有效速度用于克服底层控制器的小指令死区。到达后停车驻留，再切换下一路点。
超时超过重试次数或检测到倾斜超限时进入 `FAILED` 并持续停车。

## License

Apache-2.0。Lite3 官方软件及模型不包含在本许可证范围内。
