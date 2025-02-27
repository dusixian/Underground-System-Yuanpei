# YWolfeee:
# 本py文件保留所有需要与scheduler交互的函数。
from Appointment import global_info
from apscheduler.schedulers.background import BackgroundScheduler
from django_apscheduler.jobstores import DjangoJobStore, register_events, register_job


from Appointment.models import Student, Room, Appoint, College_Announcement
from django.http import JsonResponse, HttpResponse  # Json响应
from django.shortcuts import render, redirect  # 网页render & redirect
from django.urls import reverse
from datetime import datetime, timedelta, timezone, time, date
from django.db import transaction  # 原子化更改数据库
import Appointment.utils.utils as utils
import Appointment.utils.web_func as web_func

'''
YWolfeee:
scheduler_func.py是所有和scheduler定时任务发生交互的函数集合。
本py文件中的所有函数，或者发起了一个scheduler任务，或者删除了一个scheduler任务。
这些函数大多对应预约的开始、结束，微信的定时发送等。
如果需要实现新的函数，建议先详细阅读本py中其他函数的实现方式。
'''

# 定时任务生成器
scheduler = BackgroundScheduler()
scheduler.add_jobstore(DjangoJobStore(), "default")


# 每周清除预约的程序，会写入logstore中
@register_job(scheduler, 'cron', id='ontime_delete', day_of_week='sat', hour='3', minute="30", second='0', replace_existing=True)
def clear_appointments():
    if global_info.delete_appoint_weekly:   # 是否清除一周之前的预约
        appoints_to_delete = Appoint.objects.filter(
            Afinish__lte=datetime.now()-timedelta(days=7))
        try:
            # with transaction.atomic(): //不采取原子操作
            write_before_delete(appoints_to_delete)  # 删除之前写在记录内
            appoints_to_delete.delete()
        except Exception as e:
            utils.operation_writer(global_info.system_log, "定时删除任务出现错误: "+str(e),
                             "func[clear_appointments]", "Problem")

        # 写入日志
        utils.operation_writer(global_info.system_log, "定时删除任务成功", "func[clear_appointments]")



def cancel_scheduler(aid):  # models.py中使用
    try:
        scheduler.remove_job(f'{aid}_finish')
        try:
            scheduler.remove_job(f'{aid}_start_wechat')
        except:pass
        return JsonResponse({'statusInfo': {
            'message': '删除成功!',
        }},
            json_dumps_params={'ensure_ascii': False},
            status=200)
    except:
        return JsonResponse({'statusInfo': {
            'message': '删除计划不存在!',
        }},
            json_dumps_params={'ensure_ascii': False},
            status=400)



def cancelFunction(request):  # 取消预约
    
    warn_code = 0
    try:
        Aid = request.POST.get('cancel_btn')
        appoints = Appoint.objects.filter(Astatus=Appoint.Status.APPOINTED)
        appoint = appoints.get(Aid=Aid)
    except:
        warn_code = 1
        warning = "预约不存在、已经开始或者已取消!"
        # return render(request, 'Appointment/admin-index.html', locals())
        return redirect(
            reverse("Appointment:admin_index") + "?warn_code=" +
            str(warn_code) + "&warning=" + warning)

    try:
        assert appoint.major_student.Sid == request.session['Sid']
    except:
        warn_code = 1
        warning = "请不要恶意尝试取消不是自己发起的预约！"
        # return render(request, 'Appointment/admin-index.html', locals())
        return redirect(
            reverse("Appointment:admin_index") + "?warn_code=" +
            str(warn_code) + "&warning=" + warning)

    if appoint.Astart < datetime.now() + timedelta(minutes=30):
        warn_code = 1
        warning = "不能取消开始时间在30分钟之内的预约!"
        return redirect(
            reverse("Appointment:admin_index") + "?warn_code=" +
            str(warn_code) + "&warning=" + warning)
    # 先准备发送人
    stu_list = [stu.Sid for stu in appoint.students.all()]
    with transaction.atomic():
        appoint_room_name = appoint.Room.Rtitle
        appoint.cancel()
        try:
            scheduler.remove_job(f'{appoint.Aid}_finish')
        except:
            utils.operation_writer(global_info.system_log, "预约"+str(appoint.Aid) +
                             "取消时发现不存在计时器", 'func[cancelAppoint]', "Problem")
        utils.operation_writer(appoint.major_student.Sid, "取消了预约" +
                         str(appoint.Aid), "func[cancelAppoint]", "OK")
        warn_code = 2
        warning = "成功取消对" + appoint_room_name + "的预约!"
    # send_status, err_message = utils.send_wechat_message([appoint.major_student.Sid],appoint.Astart,appoint.Room,"cancel")
    # todo: to all
        print('will send cancel message')
        scheduler.add_job(utils.send_wechat_message,
                          args=[stu_list,
                                appoint.Astart,
                                appoint.Room,
                                "cancel",
                                appoint.major_student.Sname,
                                appoint.Ausage,
                                appoint.Aannouncement,
                                appoint.Anon_yp_num+appoint.Ayp_num,
                                '',
                                #appoint.major_student.Scredit,
                                ],
                          id=f'{appoint.Aid}_cancel_wechat',
                          next_run_time=datetime.now() + timedelta(seconds=5))
    '''
    if send_status == 1:
        # 记录错误信息
        utils.operation_writer(global_info.system_log, "预约" +
                             str(appoint.Aid) + "取消时向微信发消息失败，原因："+err_message, "func[addAppoint]", "Problem")
    '''

    # cancel wechat scheduler
    try:
        scheduler.remove_job(f'{appoint.Aid}_start_wechat')
    except:
        utils.operation_writer(global_info.system_log, "预约"+str(appoint.Aid) +
                         "取消时发现不存在wechat计时器，但也可能本来就没有", 'func[cancelAppoint]', "Problem")

    return redirect(
        reverse("Appointment:admin_index") + "?warn_code=" + str(warn_code) +
        "&warning=" + warning)


def addAppoint(contents):  # 添加预约, main function

    # 首先检查房间是否存在
    try:
        room = Room.objects.get(Rid=contents['Rid'])
        assert room.Rstatus == Room.Status.PERMITTED, 'room service suspended!'
    except Exception as e:
        return JsonResponse(
            {
                'statusInfo': {
                    'message': '房间不存在或当前房间暂停预约服务,请更换房间!',
                    'detail': str(e)
                }
            },
            status=400)
    # 再检查学号对不对
    students_id = contents['students']  # 存下学号列表
    students = Student.objects.filter(
        Sid__in=students_id).distinct()  # 获取学生objects
    try:
        assert len(students) == len(
            students_id), "students repeat or don't exists"
    except Exception as e:
        return JsonResponse(
            {
                'statusInfo': {
                    'message': '预约人信息有误,请检查后重新发起预约!',
                    'detail': str(e)
                }
            },
            status=400)

    # 检查人员信息
    try:
        #assert len(students) >= room.Rmin, f'at least {room.Rmin} students'
        real_min = room.Rmin if datetime.now().date(
        ) != contents['Astart'].date() else min(global_info.today_min, room.Rmin)
        assert len(students) + contents[
            'non_yp_num'] >= real_min, f'at least {room.Rmin} students'
    except Exception as e:
        return JsonResponse(
            {'statusInfo': {
                'message': '使用总人数需达到房间最小人数!',
                'detail': str(e)
            }},
            status=400)
    # 检查外院人数是否过多
    try:
        # assert len(
        #    students) >= contents['non_yp_num'], f"too much non-yp students!"
        assert 2 * len(
            students) >= real_min, f"too little yp students!"
    except Exception as e:
        return JsonResponse(
            {'statusInfo': {
                # 'message': '外院人数不得超过总人数的一半!',
                'message': '院内使用人数需要达到房间最小人数的一半!',
                'detail': str(e)
            }},
            status=400)

    # 检查如果是俄文楼，是否只有一个人使用
    if "R" in room.Rid:  # 如果是俄文楼系列
        try:
            assert len(
                students) + contents['non_yp_num'] == 1, f"too many people using russian room!"
        except Exception as e:
            return JsonResponse(
                {'statusInfo': {
                    'message': '俄文楼元创空间仅支持单人预约!',
                    'detail': str(e)
                }},
                status=400)

    # 检查预约时间是否正确
    try:
        #Astart = datetime.strptime(contents['Astart'], '%Y-%m-%d %H:%M:%S')
        #Afinish = datetime.strptime(contents['Afinish'], '%Y-%m-%d %H:%M:%S')
        Astart = contents['Astart']
        Afinish = contents['Afinish']
        assert Astart <= Afinish, 'Appoint time error'
        assert Astart > datetime.now(), 'Appoint time error'
    except Exception as e:
        return JsonResponse(
            {
                'statusInfo': {
                    'message': '非法预约时间段,请不要擅自修改url!',
                    'detail': str(e)
                }
            },
            status=400)
    # 预约是否超过3小时
    try:
        assert Afinish <= Astart + timedelta(hours=3)
    except:
        return JsonResponse({'statusInfo': {
            'message': '预约时常不能超过3小时!',
        }},
            status=400)
    # 学号对了，人对了，房间是真实存在的，那就开始预约了


    # 接下来开始搜索数据库，上锁
    try:
        with transaction.atomic():
            # 等待确认的和结束的肯定是当下时刻已经弄完的，所以不用管
            print("得到搜索列表")
            appoints = room.appoint_list.select_for_update().exclude(
                Astatus=Appoint.Status.CANCELED).filter(
                    Room_id=contents['Rid'])
            for appoint in appoints:
                start = appoint.Astart
                finish = appoint.Afinish

                # 第一种可能，开始在开始之前，只要结束的比开始晚就不行
                # 第二种可能，开始在开始之后，只要在结束之前就都不行
                if (start <= Astart < finish) or (Astart <= start < Afinish):
                    # 有预约冲突的嫌疑，但要检查一下是不是重复预约了
                    if start == Astart and finish == Afinish and appoint.Ausage == contents['Ausage'] \
                            and appoint.Aannouncement == contents['announcement'] and appoint.Ayp_num == len(students) \
                            and appoint.Anon_yp_num == contents['non_yp_num'] and contents['Sid'] == appoint.major_student_id:
                        # Room不用检查，肯定是同一个房间
                        utils.operation_writer(
                            major_student.Sid, "重复发起同时段预约，预约号"+str(appoint.Aid), "func[addAppoint]", "OK")
                        return JsonResponse({'data': appoint.toJson()}, status=200)
                    else:
                        # 预约冲突
                        return JsonResponse(
                            {
                                'statusInfo': {
                                    'message': '预约时间与已有预约冲突,请重选时间段!',
                                    'detail': appoint.toJson()
                                }
                            },
                            status=400)
            # 获取预约发起者,确认预约状态
            try:
                major_student = Student.objects.get(Sid=contents['Sid'])
            except:
                return JsonResponse(
                    {
                        'statusInfo': {
                            'message': '发起人信息与登录信息不符,请不要在同一浏览器同时登录不同账号!',
                        }
                    },
                    status=400)

            # 确认信用分符合要求
            try:
                assert major_student.Scredit > 0
            except:
                return JsonResponse(
                    {'statusInfo': {
                        'message': '信用分不足,本月无法发起预约!',
                    }},
                    status=400)

            # 合法，可以返回了
            appoint = Appoint(Room=room,
                              Astart=Astart,
                              Afinish=Afinish,
                              Ausage=contents['Ausage'],
                              Aannouncement=contents['announcement'],
                              major_student=major_student,
                              Anon_yp_num=contents['non_yp_num'],
                              Ayp_num=len(students))
            appoint.save()
            for student in students:
                appoint.students.add(student)
            appoint.save()

            # write by cdf start2  # 添加定时任务：finish
            scheduler.add_job(web_func.finishFunction,
                              args=[appoint.Aid],
                              id=f'{appoint.Aid}_finish',
                              next_run_time=Afinish)  # - timedelta(minutes=45))
            # write by cdf end2
            if datetime.now() <= appoint.Astart - timedelta(minutes=15):  # 距离预约开始还有15分钟以上，提醒有新预约&定时任务
                print('距离预约开始还有15分钟以上，提醒有新预约&定时任务', contents['new_require'])
                if contents['new_require'] == 1:  # 只有在非长线预约中才添加这个job
                    scheduler.add_job(utils.send_wechat_message,
                                      args=[students_id,
                                            appoint.Astart,
                                            appoint.Room,
                                            "new",
                                            appoint.major_student.Sname,
                                            appoint.Ausage,
                                            appoint.Aannouncement,
                                            appoint.Anon_yp_num+appoint.Ayp_num,
                                            '',
                                            # appoint.major_student.Scredit,
                                            ],
                                      id=f'{appoint.Aid}_new_wechat',
                                      next_run_time=datetime.now() + timedelta(seconds=5))
                scheduler.add_job(utils.send_wechat_message,
                                  args=[students_id,
                                        appoint.Astart,
                                        appoint.Room,
                                        "start",
                                        appoint.major_student.Sname,
                                        appoint.Ausage,
                                        appoint.Aannouncement,
                                        appoint.Ayp_num+appoint.Anon_yp_num,
                                        '',
                                        # appoint.major_student.Scredit,
                                        ],
                                  id=f'{appoint.Aid}_start_wechat',
                                  next_run_time=appoint.Astart - timedelta(minutes=15))
            else:  # 距离预约开始还有不到15分钟，提醒有新预约并且马上开始
                # send_status, err_message = utils.send_wechat_message(students_id, appoint.Astart, appoint.Room,"new&start")
                scheduler.add_job(utils.send_wechat_message,
                                  args=[students_id,
                                        appoint.Astart,
                                        appoint.Room,
                                        "new&start",
                                        appoint.major_student.Sname,
                                        appoint.Ausage,
                                        appoint.Aannouncement,
                                        appoint.Anon_yp_num+appoint.Ayp_num,
                                        '',
                                        # appoint.major_student.Scredit,
                                        ],
                                  id=f'{appoint.Aid}_new_wechat',
                                  next_run_time=datetime.now() + timedelta(seconds=5))

            utils.operation_writer(major_student.Sid, "发起预约，预约号" +
                             str(appoint.Aid), "func[addAppoint]", "OK")

    except Exception as e:
        utils.operation_writer(global_info.system_log, "学生" + str(major_student) +
                         "出现添加预约失败的问题:"+str(e), "func[addAppoint]", "Error")
        return JsonResponse({'statusInfo': {
            'message': '添加预约失败!请与管理员联系!',
        }},
            status=400)

    return JsonResponse({'data': appoint.toJson()}, status=200)