const IS_DEBUG = import.meta.env.DEV;
//바이트가 부여해준다.( 개발모드는 디버그모드)

export const DebugManager = {

 /**
   * 람다를 감싸서 디버그 모드일 때만 알람을 띄우고 실행하는 메서드입니다.
   * @param {string} message - 알람에 표시할 메시지
   * @param {Function} lambda - 실행할 실제 로직 (람다 식)
   */
    DebugAlarm(message, lambda = ()=>{}){
        if(true != IS_DEBUG) return 
        alert(`[DEBUG]:${message}`)
        return lambda(); 
        //실행의 결과물을 반환합니다.
    },
    DebugConsolelog(TAG, message, ...args) {
    if (!IS_DEBUG) return;
    console.log(`[DEBUG] [${TAG}] : ${message}`, ...args);
}

}