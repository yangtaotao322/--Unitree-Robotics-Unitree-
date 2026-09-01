#include <cstdlib>
#include <chrono>
#include <iostream>
#include <string>
#include <thread>

#include <unitree/robot/channel/channel_subscriber.hpp>
#include <unitree/robot/g1/audio/g1_audio_client.hpp>
#include <unitree/idl/ros2/String_.hpp>

static void asr_handler(const void *msg) {
  std_msgs::msg::dds_::String_ *res = (std_msgs::msg::dds_::String_ *)msg;
  std::string raw = res->data();
  if (raw.find("play_state") == std::string::npos) {
    size_t p = raw.find("\"text\"");
    if (p != std::string::npos) {
      size_t a = raw.find(":", p) + 1;
      while (a < raw.size() && (raw[a] == ' ' || raw[a] == '"')) a++;
      size_t b = a;
      while (b < raw.size() && raw[b] != '"') b++;
      std::cout << "ASR_TEXT:" << raw.substr(a, b - a) << std::endl;
    } else {
      std::cout << "ASR_RAW:" << raw << std::endl;
    }
    std::cout.flush();
  }
}

int main(int argc, char const *argv[]) {
  if (argc < 3) {
    std::cout << "Usage:" << std::endl;
    std::cout << "  g1_voice <iface> say <text...>" << std::endl;
    std::cout << "  g1_voice <iface> hear" << std::endl;
    exit(0);
  }
  unitree::robot::ChannelFactory::Instance()->Init(0, argv[1]);
  unitree::robot::g1::AudioClient client;
  client.Init();
  client.SetTimeout(10.0f);
  std::string cmd = argv[2];
  if (cmd == "say") {
    std::string text;
    for (int i = 3; i < argc; ++i) {
      if (i > 3) text += " ";
      text += argv[i];
    }
    int spk = 0;
    const char *env = getenv("TTS_SPEAKER");
    if (env) spk = atoi(env);
    int ret = client.TtsMaker(text, spk);
    std::cout << "TTS_RET:" << ret << std::endl;
    std::cout.flush();
    /* TtsMaker 是异步的,保持进程存活 4 秒让播放完成 */
    std::this_thread::sleep_for(std::chrono::seconds(4));
    return 0;
  }
  if (cmd == "hear") {
    uint8_t vol = 0;
    client.GetVolume(vol);
    std::cout << "VOLUME:" << (int)vol << std::endl;
    unitree::robot::ChannelSubscriber<std_msgs::msg::dds_::String_> subscriber(
        "rt/audio_msg");
    subscriber.InitChannel(asr_handler);
    std::cout << "LISTENING" << std::endl;
    std::cout.flush();
    while (true) {
      std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }
  }
  return 0;
}