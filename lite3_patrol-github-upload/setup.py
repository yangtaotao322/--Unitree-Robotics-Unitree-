from setuptools import find_packages, setup

package_name = 'lite3_patrol'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', ['config/sim.yaml', 'config/real_low_speed.yaml']),
        ('share/' + package_name + '/launch', ['launch/patrol.launch.py']),
        ('share/' + package_name + '/docs', ['docs/LITE3_INTEGRATION.md']),
        ('share/' + package_name + '/integration',
         ['integration/gazebo_ground_truth_plugin.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Lite3 Patrol Contributors',
    maintainer_email='maintainer@example.com',
    description='Lite3 patrol state machine for Gazebo and staged real testing',
    license='Apache-2.0',
    entry_points={'console_scripts': ['patrol_node = lite3_patrol.patrol_node:main']},
)
