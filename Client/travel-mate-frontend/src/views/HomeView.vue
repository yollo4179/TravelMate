<template>
  <h1>홈 화면</h1>
  <p>여기는 홈 화면입니다. 로그인 여부에 따라 다른 콘텐츠를 보여줄 수 있습니다.</p>
</template>

<script setup></script>

<style scoped>
/* Scrollbar configurations for clean layout */
.scrollbar-none::-webkit-scrollbar {
  display: none;
}
.scrollbar-none {
  -ms-overflow-style: none;
  scrollbar-width: none;
}
.scrollbar-thin::-webkit-scrollbar {
  width: 4px;
}
.scrollbar-thin::-webkit-scrollbar-track {
  background: transparent;
}
.scrollbar-thin::-webkit-scrollbar-thumb {
  background: #334155;
  border-radius: 9999px;
}
</style>
