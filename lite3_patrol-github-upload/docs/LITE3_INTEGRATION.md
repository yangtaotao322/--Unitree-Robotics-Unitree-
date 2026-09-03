# Lite3 仿真接入说明

## 控制接口

巡检节点默认向 `/cmd_vel` 发布 `geometry_msgs/msg/Twist`。Lite3 控制器必须处于能够消费
该话题的导航/行走模式。若节点运行但模型不移动，先检查：

```bash
ros2 topic info /cmd_vel -v
```

然后确认机器人已经起身、进入行走状态并开启 Navigation 模式。

## Ground Truth 里程计

默认配置读取 `/ground_truth/odom`。若原模型没有该话题，可把
`integration/gazebo_ground_truth_plugin.xml` 的插件片段加入机器人 Gazebo xacro 的
`<gazebo>` 元素内。根据模型修改 `bodyName`，它必须是实际存在的机身 link。

重新构建并启动后验证：

```bash
ros2 topic echo /ground_truth/odom --once
```

若项目已有可靠 `/odom`，可直接修改 `config/sim.yaml` 的 `pose_topic`，无需添加插件。

## 场景选择

基础巡检应先在平坦场景完成。楼梯、斜坡或障碍场景需要地形感知和适配的运动策略，不能
只依靠二维路点控制。Gazebo world 由 Lite3 仿真项目自身的 launch 文件选择，本仓库不
复制厂商资源。

## 常见问题

### 有 `/cmd_vel` 但机器人不动

- 控制器未进入 Navigation 模式。
- `/cmd_vel` 没有订阅者或命名空间不同。
- 指令低于底层控制器死区，可谨慎调高 `min_linear_speed`。
- Gazebo 处于暂停状态或控制器进程已经退出。

### 靠近目标但一直不到点

- 定位噪声大于 `position_tolerance`。
- 最低速度太小，无法驱动机器人。
- 最低速度太大，造成来回越过目标。

每次只调整 `position_tolerance` 或 `min_linear_speed` 中的一个，并保存日志比较。

### 转弯翻倒

- 降低 `max_angular_speed` 和 `max_linear_speed`。
- 先转向、再直行，避免高速急转。
- 在平地重新验证初始姿态和控制状态。
- 保留 `fall_angle_threshold` 保护。
