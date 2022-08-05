# -*- coding: utf-8 -*-

##############################################################################
#
#    Clear Groups for Odoo
#    Copyright (C) 2016 Bytebrand GmbH (<http://www.bytebrand.net>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Lesser General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

import datetime as dtime

from datetime import datetime, timedelta
from odoo import api, fields, models, _
from dateutil import rrule, parser
from odoo.tools.translate import _


class Sheet(models.Model):
    """
        Addition plugin for HR timesheet for work with duty hours
    """
    _name = "hr_timesheet.sheet"
    _inherit = 'hr_timesheet.sheet'
    
    def _duty_hours(self):
        for sheet in self:
            sheet['total_duty_hours'] = 0.0
            if sheet.state == 'done' and 'total_duty_hours_done' in sheet and sheet['total_duty_hours_done']:
                sheet['total_duty_hours'] = sheet['total_duty_hours_done']
            else:
                dates = list(rrule.rrule(rrule.DAILY,
                                         dtstart=sheet.date_start,
                                         until=sheet.date_end))
                period = {'date_start': sheet.date_start,
                          'date_end': sheet.date_end}
                for date_line in dates:
                    duty_hours = sheet.calculate_duty_hours(date_start=date_line,
                                                            period=period,
                                                            )
                    sheet['total_duty_hours'] += duty_hours
                sheet['total_duty_hours_done'] = sheet['total_duty_hours']
    
    
    def count_leaves(self, date_start, employee_id, period):
        holiday_obj = self.env['hr.holidays']
        start_leave_period = end_leave_period = False
        if period.get('date_start') and period.get('date_end'):
            start_leave_period = period.get('date_start')
            end_leave_period = period.get('date_end')
        holiday_ids = holiday_obj.search(
            ['|', '&',
             ('date_start', '>=', start_leave_period),
             ('date_start', '<=', end_leave_period),
             '&', ('date_end', '<=', end_leave_period),
             ('date_end', '>=', start_leave_period),
             ('employee_id', '=', employee_id),
             ('state', '=', 'validate'),
             ('type', '=', 'remove')])
        leaves = []
        for leave in holiday_ids:
            leave_date_start = datetime.strptime(leave.date_start,
                                                '%Y-%m-%d %H:%M:%S')
            leave_date_end = datetime.strptime(leave.date_end,
                                              '%Y-%m-%d %H:%M:%S')
            leave_dates = list(rrule.rrule(rrule.DAILY,
                                           dtstart=parser.parse(
                                               leave.date_start),
                                           until=parser.parse(leave.date_end)))
            for date in leave_dates:
                if date.strftime('%Y-%m-%d') == date_start.strftime('%Y-%m-%d'):
                    leaves.append(
                        (leave_date_start, leave_date_end, leave.number_of_days))
                    break
        return leaves
    
    
    def get_overtime(self, start_date):
        for sheet in self:
            if sheet.state == 'done':
                return sheet.total_time - sheet.total_duty_hours_done
            return self.calculate_diff(start_date)
    
    
    def _overtime_diff(self):
        for sheet in self:
            # What is this? why day and not month?
            old_timesheet_start_from = parser.parse(
                sheet.date_start) - timedelta(days=1)
            prev_timesheet_diff = \
                self.get_previous_month_diff(
                    sheet.employee_id.id,
                    old_timesheet_start_from.strftime('%Y-%m-%d')
                )
            sheet['calculate_diff_hours'] = (
                self.get_overtime(datetime.today().strftime('%Y-%m-%d'), ) +
                prev_timesheet_diff)
            sheet['prev_timesheet_diff'] = prev_timesheet_diff
    
    # Pupulate Overtime Analysis table data with results from attendance_analysis
    
    def _get_analysis(self):
        res = {}
        for sheet in self:
            function_call = True
            data = self.attendance_analysis(sheet.id, function_call)
            values = []
            output = [
                '<style>.attendanceTable td,.attendanceTable th {padding: 3px; border: 1px solid #C0C0C0; border-collapse: collapse;     text-align: right;} </style><table class="attendanceTable" >']
            for val in data.values():
                if isinstance(val, (int, float)):
                    output.append('<tr>')
                    prev_ts = _('Previous Timesheet:')
                    output.append('<th colspan="2">' + prev_ts + ' </th>')
                    output.append('<td colspan="3">' + str(val) + '</td>')
                    output.append('</tr>')
            for k, v in data.items():
                if isinstance(v, list):
                    output.append('<tr>')
                    for th in v[0].keys():
                        output.append('<th>' + th + '</th>')
                    output.append('</tr>')
                    for res in v:
                        values.append(res.values())
                    for tr in values:
                        output.append('<tr>')
                        for td in tr:
                            output.append('<td>' + td + '</td>')
                        output.append('</tr>')
    
                if isinstance(v, dict):
                    output.append('<tr>')
                    total_ts = _('Total:')
                    output.append('<th>' + total_ts + ' </th>')
                    for td in v.values():
                        output.append('<td>' + '%s' % round(td, 4) + '</td>')
                    output.append('</tr>')
            output.append('</table>')
            sheet['analysis'] = '\n'.join(output)
    
    # This used to start as "expected to be done" and finish as "monthly diff"
    # Now this will remain as the expected time always.
    total_duty_hours = fields.Float(compute='_duty_hours',
                                    string='Total Duty Hours')
    # Remains as cache of the total_duty_hours.
    total_duty_hours_done = fields.Float(string='Total Duty Hours',
                                         readonly=True,
                                         default=0.0)
    # What is this for?
    total_diff_hours = fields.Float(string='Total Diff Hours',
                                    readonly=True,
                                    default=0.0)
    # This is the "Total balance", the final result considering all past deltas.
    calculate_diff_hours = fields.Float(compute='_overtime_diff',
                                       string="Diff (worked-duty)")
    # This is the delta of the previous month.
    prev_timesheet_diff = fields.Float(compute='_overtime_diff',
                                      string="Diff from old")
    # This constructs the "Overtime Analysys" tab content (table)
    analysis = fields.Text(compute='_get_analysis',
                           type="text",
                           string="Attendance Analysis")
    
    
    def calculate_duty_hours(self, date_start, period):
        contract_obj = self.env['hr.contract']
        calendar_obj = self.env['resource.calendar']
        duty_hours = 0.0
        contract_ids = contract_obj.search(
            [('employee_id', '=', self.employee_id.id),
             ('date_start', '<=', date_start), '|',
             ('date_end', '>=', date_start),
             ('date_end', '=', None),
             ('state', 'not in', ('draft', 'cancel'))])
        for contract in contract_ids:
            if contract and contract.rate_per_hour:
                return 0.00
            ctx = dict(self.env.context).copy()
            ctx.update(period)
            if contract:
                dh = contract.resource_calendar_id.get_working_hours_of_date(
                    start_dt=fields.Datetime.from_string(date_start),
                    resource_id=self.employee_id.id)
            else:
                dh = 00.00
            leaves = self.count_leaves(date_start, self.employee_id.id, period)
            if not leaves:
                if not dh:
                    dh = 0.00
                duty_hours += dh
            else:
                if leaves[-1] and leaves[-1][-1]:
                    if float(leaves[-1][-1]) == (-0.5):
                        duty_hours += dh / 2
    
        return duty_hours
    
    
    def get_previous_month_diff(self, employee_id, prev_timesheet_date_start):
        total_diff = 0.0
        timesheet_ids = self.search(
            [('employee_id', '=', employee_id),
             ('date_start', '<', prev_timesheet_date_start)
             ])
        for timesheet in timesheet_ids:
            total_diff += timesheet.get_overtime(
                start_date=prev_timesheet_date_start)
        return total_diff
    
    
    def _get_user_datetime_format(self):
        """ Get user's language & fetch date/time formats of
        that language """
        lang_obj = self.env['res.lang']
        language = self.env.user.lang
        lang_ids = lang_obj.search([('code', '=', language)])
        date_format = _('%Y-%m-%d')
        time_format = _('%H:%M:%S')
        for lang in lang_ids:
            date_format = lang.date_format
            time_format = lang.time_format
        return date_format, time_format
    
    
    def attendance_analysis(self, timesheet_id=None, function_call=False):
        attendance_obj = self.env['hr.attendance']
        date_format, time_format = self._get_user_datetime_format()
    
        for sheet in self:
            if sheet.id == timesheet_id:
    
                employee_id = sheet.employee_id.id
                start_date = sheet.date_start
                end_date = sheet.date_end
                previous_month_diff = self.get_previous_month_diff(
                    employee_id, start_date)
                current_month_diff = previous_month_diff
                res = {
                    'previous_month_diff': previous_month_diff,
                    'hours': []
                }
    
                period = {'date_start': start_date,
                          'date_end': end_date
                          }
                dates = list(rrule.rrule(rrule.DAILY,
                                         dtstart=parser.parse(start_date),
                                         until=parser.parse(
                                             end_date)))
                work_current_month_diff = 0.0
                total = {'worked_hours': 0.0, 'duty_hours': 0.0,
                         'diff':
                             current_month_diff, 'work_current_month_diff': ''}
                for date_line in dates:
    
                    dh = sheet.calculate_duty_hours(date_start=date_line,
                                                    period=period,
                                                    )
                    worked_hours = 0.0
                    for att in sheet.period_ids:
                        if att.name == date_line.strftime('%Y-%m-%d'):
                            worked_hours = att.total_time
    
                    diff = worked_hours - dh
                    current_month_diff += diff
                    work_current_month_diff += diff
                    if function_call:
                        res['hours'].append({
                            _('Date'): date_line.strftime(date_format),
                            _('Duty Hours'):
                                attendance_obj.float_time_convert(dh),
                            _('Worked Hours'):
                                attendance_obj.float_time_convert(worked_hours),
                            _('Difference'): self.sign_float_time_convert(diff),
                            _('Running'): self.sign_float_time_convert(
                                current_month_diff)})
                    else:
                        res['hours'].append({
                            'name': date_line.strftime(date_format),
                            'dh': attendance_obj.float_time_convert(dh),
                            'worked_hours': attendance_obj.float_time_convert(
                                worked_hours),
                            'diff': self.sign_float_time_convert(diff),
                            'running': self.sign_float_time_convert(
                                current_month_diff)
                        })
                    total['duty_hours'] += dh
                    total['worked_hours'] += worked_hours
                    total['diff'] += diff
                    total['work_current_month_diff'] = work_current_month_diff
                    res['total'] = total
                return res
    
    
    def sign_float_time_convert(self, float_time):
        sign = '-' if float_time < 0 else ''
        attendance_obj = self.pool.get('hr.attendance')
        return sign + attendance_obj.float_time_convert(float_time)
    
    
    def write(self, vals):
        if 'state' in vals and vals['state'] == 'done':
            for sheet in self:
                vals['total_diff_hours'] = sheet.calculate_diff_hours
                vals['total_duty_hours_done'] = sheet['total_duty_hours_done']
        elif 'state' in vals and vals['state'] == 'draft':
            for sheet in self:
                vals['total_diff_hours'] = sheet.calculate_diff_hours
        res = super(Sheet, self).write(vals)
        return res
    
    
    def calculate_diff(self, end_date=None):
        for sheet in self:
            return (sheet.total_time - sheet.total_duty_hours)
