#include "blur/blur.h"
#include <chrono>
#include <cstring>
#include <iostream>
#include <png.h>
#include <vector>

bool read_png_file(const char *filename, std::vector<uint8_t> &buffer,
    int &width, int &height) {
  FILE *fp = fopen(filename, "rb");
  if (!fp)
    return false;

  png_structp png =
    png_create_read_struct(PNG_LIBPNG_VER_STRING, NULL, NULL, NULL);
  if (!png)
    return false;

  png_infop info = png_create_info_struct(png);
  if (!info)
    return false;

  if (setjmp(png_jmpbuf(png)))
    return false;

  png_init_io(png, fp);
  png_read_info(png, info);

  width = png_get_image_width(png, info);
  height = png_get_image_height(png, info);
  buffer.resize(width * height);

  png_bytep row = new png_byte[width];

  for (int y = 0; y < height; y++) {
    png_read_row(png, row, NULL);
    for (int x = 0; x < width; x++) {
      buffer[y * width + x] = row[x];
    }
  }

  fclose(fp);

  if (png && info)
    png_destroy_read_struct(&png, &info, NULL);

  delete[] row;

  return true;
}

bool write_png_file(
    const char *filename, const uint8_t *buffer, int width, int height) {
  FILE *fp = fopen(filename, "wb");
  if (!fp)
    return false;

  png_structp png =
    png_create_write_struct(PNG_LIBPNG_VER_STRING, NULL, NULL, NULL);
  if (!png)
    return false;

  png_infop info = png_create_info_struct(png);
  if (!info)
    return false;

  if (setjmp(png_jmpbuf(png)))
    return false;

  png_init_io(png, fp);

  // Bit depth is usually 8 for grayscale images, 1/2/4/16 are also possible.
  png_set_IHDR(png, info, width, height, 8, PNG_COLOR_TYPE_GRAY,
      PNG_INTERLACE_NONE, PNG_COMPRESSION_TYPE_BASE, PNG_FILTER_TYPE_BASE);

  png_write_info(png, info);

  png_bytep row = new png_byte[width];

  for (int y = 0; y < height; y++) {
    for (int x = 0; x < width; x++) {
      row[x] = buffer[y * width + x];
    }
    png_write_row(png, row);
  }

  png_write_end(png, NULL);
  fclose(fp);

  if (png && info)
    png_destroy_write_struct(&png, &info);

  delete[] row;

  return true;
}

typedef void (*blurtype)(
    void *ctxt, int_fast32_t n, uint8_t *g, const uint8_t *inp);

int exec_parrot(blurtype func, std::string output_name, int width, int height,
    uint8_t *parrot) {
  uint8_t *parrot_blurred;
  parrot_blurred = (uint8_t *)malloc(sizeof(uint8_t) * width * height);

  auto start = std::chrono::steady_clock::now();
  int iterations = 100;
  for (int i = 0; i < iterations; i++)
    func(nullptr, width * height, parrot_blurred, parrot);
  auto stop = std::chrono::steady_clock::now();
  float time = (float)std::chrono::duration_cast<std::chrono::microseconds>(
      (stop - start) / iterations)
                   .count();
  printf("%s: %f microseconds\n", output_name.c_str(), time);

  std::string file_name = output_name + std::string(".png");
  if (!write_png_file(file_name.c_str(), parrot_blurred, width, height)) {
    std::cerr << "Error writing PNG file." << std::endl;
  }

  return 0;
}

int main() {
  const char* read_file = "gray.png";
  std::vector<uint8_t> buffer;
  int width, height;

  if(read_png_file(read_file, buffer, width, height)) {
    printf("width: %d\n", (int)width);
    printf("height: %d\n", (int)height);

    uint8_t *parrot;
    parrot = (uint8_t *)malloc(sizeof(uint8_t) * width * height);
    memcpy(parrot, buffer.data(), sizeof(uint8_t) * width * height);

    exec_parrot(blur_staged, "blur_staged", width, height, parrot);
    exec_parrot(blur_compute_at_store_root, "blur_compute_at_store_root", width, height, parrot);
    exec_parrot(blur_compute_at_store_at, "blur_compute_at_store_at", width, height, parrot);
    exec_parrot(blur_inline, "blur_inline", width, height, parrot);
  } else {
    std::cerr << "Error reading PNG file." << std::endl;
  }

return 0;
}
