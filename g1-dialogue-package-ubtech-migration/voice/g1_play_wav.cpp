#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <string>
#include <vector>

#include <unitree/common/time/time_tool.hpp>
#include <unitree/robot/channel/channel_factory.hpp>
#include <unitree/robot/g1/audio/g1_audio_client.hpp>

#include "../audio/wav.hpp"

int main(int argc, char const *argv[]) {
  if (argc != 3) {
    std::cerr << "Usage: g1_play_wav <iface> <16k-mono-pcm.wav>" << std::endl;
    return 2;
  }

  unitree::robot::ChannelFactory::Instance()->Init(0, argv[1]);
  unitree::robot::g1::AudioClient client;
  client.Init();
  client.SetTimeout(10.0f);
  client.SetVolume(100);

  int32_t sample_rate = -1;
  int8_t channels = 0;
  bool ok = false;
  std::vector<uint8_t> pcm = ReadWave(argv[2], &sample_rate, &channels, &ok);
  if (!ok || sample_rate != 16000 || channels != 1 || pcm.empty()) {
    std::cerr << "WAV_FORMAT_ERROR rate=" << sample_rate
              << " channels=" << static_cast<int>(channels)
              << " bytes=" << pcm.size() << std::endl;
    return 3;
  }

  const size_t chunk_size = 32000;
  const std::string stream_id =
      std::to_string(unitree::common::GetCurrentTimeMillisecond());
  size_t offset = 0;
  while (offset < pcm.size()) {
    const size_t size = std::min(chunk_size, pcm.size() - offset);
    std::vector<uint8_t> chunk(pcm.begin() + offset,
                               pcm.begin() + offset + size);
    int32_t ret = client.PlayStream("qwen_tts", stream_id, chunk);
    std::cout << "PLAY_CHUNK ret=" << ret << " offset=" << offset
              << " size=" << size << std::endl;
    if (ret != 0) return 4;
    offset += size;
    unitree::common::Sleep(1);
  }
  unitree::common::Sleep(1);
  int32_t ret = client.PlayStop(stream_id);
  std::cout << "PLAY_STOP ret=" << ret << std::endl;
  return ret == 0 ? 0 : 5;
}
