from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'config',
            default_value=PathJoinSubstitution([
                FindPackageShare('lite3_patrol'), 'config', 'sim.yaml'
            ]),
            description='Absolute path to a patrol parameter YAML file',
        ),
        Node(
            package='lite3_patrol',
            executable='patrol_node',
            name='lite3_patrol',
            output='screen',
            parameters=[LaunchConfiguration('config')],
        ),
    ])
